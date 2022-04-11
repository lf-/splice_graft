import setuptools
import sys

import pip

pip_version = tuple([int(x) for x in pip.__version__.split('.')[:3]])
if pip_version < (9, 0, 1) :
    raise RuntimeError('Version of pip less than 9.0.1, breaking python ' \
                       'version requirement support')

setuptools.setup(
    name = 'splice_graft',
    version = '0.0.0',
    py_modules = ['splice_graft'],
    python_requires = '>=3.8',
    entry_points = {
        'console_scripts': [
            'splice-graft=splice_graft:main'
        ]
    },

    install_requires = [
        'requests'
    ],

    description = 'github api tool',
    license = 'MIT',
    url = 'https://github.com/lf-/splice_graft'
)
