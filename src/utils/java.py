"""
Most of the paths are from https://github.com/PrismLauncher/PrismLauncher/blob/develop/launcher/java/JavaUtils.cpp
"""

import os.path
import re
import shutil
import subprocess
import platform
import sys
import aiofiles
import zipfile
from dataclasses import dataclass
from pathlib import Path
from httpx import AsyncClient
from src.config import get_dirs
from src.compat import chmod_x


@dataclass
class JavaInstall:
    version: str
    path: str


@dataclass
class JavaArchive:
    package_uuid: str
    name: str
    version: list[int]
    openjdk_build_number: int
    latest: bool
    download_url: str
    product: str
    distro_version: list[int]
    availability_type: str

    @classmethod
    def from_dict(cls, data: dict) -> 'JavaArchive':
        return cls(
            package_uuid=data.get('package_uuid', ''),
            name=data.get('name', ''),
            version=data.get('version', []),
            openjdk_build_number=data.get('openjdk_build_number', 0),
            latest=data.get('latest', False),
            download_url=data.get('download_url', ''),
            product=data.get('product', ''),
            distro_version=data.get('distro_version', []),
            availability_type=data.get('availability_type', '')
        )


PKG_URL: str = 'https://api.azul.com/metadata/v1/zulu/packages/'
JAVA_VERSION_RGX = re.compile(r'"(.*)?"')
REQUIRED_JAVA = '8'


def is_good_version(java: JavaInstall) -> bool:
    return java.version == '1.8.0' or java.version.startswith('1.8.0')


def check_java(path: JavaInstall | str | Path) -> JavaInstall | None:
    if isinstance(path, JavaInstall):
        path = path.path
    elif isinstance(path, Path):
        path = str(path)
    path = shutil.which(path)
    if not path or not os.path.isfile(path):
        return None
    try:
        version_result = subprocess.check_output(
            [path, '-version'], stderr=subprocess.STDOUT
        ).decode()
    except subprocess.CalledProcessError:
        return None
    match = JAVA_VERSION_RGX.search(version_result)
    if not match:
        return None
    version = match.group(1)
    return JavaInstall(
        path=path,
        version=version,
    )


def apply_arguments_to_url(endpoint: str, args: dict) -> str:
    url = endpoint + '?'
    for key in args.keys():
        url += f'{key}={args.get(key)}&'
    return url


def extract(java_archive_path: str, java_output_path):
    with zipfile.ZipFile(java_archive_path, 'r') as zip_ref:
        zip_ref.extractall(java_output_path)


def get_os() -> str:
    system = sys.platform
    if system == 'darwin':
        return 'macos'
    elif system == 'win32':
        return 'windows'
    elif system == 'linux':
        return 'linux'
    return ''


def get_arch() -> str:
    arch = platform.machine()
    if arch == 'x86_64':
        return 'x64'
    elif arch == 'i686':
        return arch
    else:
        return 'aarch64'


def generate_params() -> dict:
    return {
        'java_version': '8',
        'os': get_os(),
        'arch': get_arch(),
        'archive_type': 'zip',
        'java_package_type': 'jre',
        'javafx_bundled': 'false',
        'support_term': 'lts',
        'latest': 'true',
        'release_status': 'ga'
    }


async def get_java(params: dict) -> JavaArchive:
    async with AsyncClient() as client:
        response = await client.get(apply_arguments_to_url(PKG_URL, params))
        java_archives_json = response.json()
        java_archives: list[JavaArchive] = [JavaArchive.from_dict(item) for item in java_archives_json]
        return java_archives[0]


async def download(url: str, filename: str) -> None:
    async with AsyncClient() as client:
        async with client.stream('GET', url) as response:
            async with aiofiles.open(filename, 'wb') as file:
                async for chunk in response.aiter_bytes(4096):
                    await file.write(chunk)


async def setup_java() -> str:
    java_params = generate_params()
    java = await get_java(java_params)
    if java_params['os'] == '':
        raise ValueError('Unsupported platform')

    filename: str = java.download_url.split('/')[-1]
    await download(java.download_url, filename)
    launcher_dir = get_dirs().user_data_path
    extract(filename, launcher_dir)

    os.remove(filename)

    folder_path: str = launcher_dir / filename.replace('.zip', '')

    files_to_chmod = [ f'{folder_path}/bin/{file}' for file in os.listdir(f'{folder_path}/bin') ]
    files_to_chmod.append(f'{folder_path}/lib/jexec')

    for file_to_chmod in files_to_chmod:
        chmod_x(file_to_chmod)

    java_path: str = f'/bin/java'
    if java_params['os'] == 'windows':
        java_path += 'w'

    return str(folder_path) + java_path


__all__ = ['setup_java', 'check_java']
