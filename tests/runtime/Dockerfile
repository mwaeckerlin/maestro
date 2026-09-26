# The image under test plus the runtime contract; the image has no shell to
# receive a script at run time.
FROM mwaeckerlin/maestro
COPY check_runtime.py /tests/check_runtime.py
ENTRYPOINT ["/opt/maestro/venv/bin/python", "/tests/check_runtime.py"]
