import os

path = r"C:\Program Files\mosquitto\mosquitto.conf"
with open(path, "rb") as f:
    data = f.read()

idx = data.find(b"#include_dir")
if idx != -1:
    # Keep up to the end of the line containing #include_dir
    end_idx = data.find(b"\n", idx)
    if end_idx != -1:
        data = data[:end_idx+1]
    else:
        data = data[:idx + len(b"#include_dir")]
        data += b"\r\n"

# Append the required settings
data += b"listener 1883 0.0.0.0\r\n"
data += b"allow_anonymous true\r\n"

with open(path, "wb") as f:
    f.write(data)

print("mosquitto.conf fixed!")
