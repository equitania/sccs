# setup.py
from setuptools import setup, find_packages

# Version is defined here to avoid import issues during build
__version__ = "1.0.0"

setup(
    name='sccs',
    version=__version__,
    description='Skills, Commands, Configs Sync for Claude Code - bidirectional synchronization tool.',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    author='Equitania Software GmbH',
    author_email='info@equitania.de',
    url='https://github.com/equitania/sccs',
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        'click>=8.1.0',
        'rich>=13.0.0',
        'PyYAML>=6.0',
    ],
    entry_points={
        'console_scripts': [
            'sccs = sccs.cli:cli',
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "License :: OSI Approved :: GNU Affero General Public License v3",
        "Operating System :: OS Independent",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Version Control",
        "Topic :: Utilities",
    ],
    python_requires='>=3.10',
    keywords='claude, skills, commands, sync, configuration',
)
