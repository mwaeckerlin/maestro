# The image under test with the GPU-free harness as entrypoint.
FROM mwaeckerlin/maestro
COPY harness.py /tests/harness.py
ENTRYPOINT ["/opt/maestro/venv/bin/python", "/tests/harness.py"]
