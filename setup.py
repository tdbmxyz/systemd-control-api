#!/usr/bin/env python

from setuptools import setup

setup(
    name="systemd-control-api",
    version="0.1.0",
    py_modules=["systemd_control_api"],
    entry_points={
        "console_scripts": [
            "systemd-control-api=systemd_control_api:main",
        ],
    },
    install_requires=[
        "fastapi",
        "uvicorn",
        "pydantic",
        "pydbus",
    ],
)
