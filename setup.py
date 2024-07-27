from setuptools import find_packages, setup

VERSION = "0.1"

INSTALL_REQUIRES = [
    "fastapi[all]==0.92.0",
    "openai-whisper==20231117",
    "setuptools-rust==1.9.0",
]

setup(
    name="audio-text",
    version=VERSION,
    python_requires=">=3.9.0",
    packages=find_packages(exclude=["tests"]),
    author="Daniel Ducuara",
    author_email="daniel14015@gmail.com",
    description="Get text from audio",
    include_package_data=True,
    entry_points={"console_scripts": []},
    install_requires=INSTALL_REQUIRES,
    extras_require={
        "dev": [
            "bandit==1.7.0",
            "mypy==0.931",
            "pre-commit==3.1.0",
            "pylint==2.7.0",
            "black==22.10.0",
            "isort==5.10.1",
            "beautysh==6.2.1",
            "autoflake==1.7.7",
        ],
        "test": [
            "pytest==6.2.4",
            "pytest-mock==3.6.1",
            "pytest-cov==2.12.1",
            "pytest-asyncio==0.15.1",
        ],
    },
)
