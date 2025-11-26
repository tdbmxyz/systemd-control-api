{python313Packages, ...}:
with python313Packages;
  buildPythonApplication {
    pname = "systemd-control-api";
    version = "0.1.0";

    propagatedBuildInputs = [
      fastapi
      uvicorn
      systemd-python
      pydantic
      pydbus
    ];

    pyproject = true;
    build-system = [setuptools];

    src = ./.;
  }
