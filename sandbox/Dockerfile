FROM python:3.12.10-slim-bookworm
RUN python -m pip install --no-cache-dir numpy==2.2.5 Pillow==11.2.1
ARG runtime_hash
LABEL voxlush.runtime=$runtime_hash
COPY backend/src/voxlush/voxel/resources/sandbox_worker.py /runtime/sandbox_worker.py
COPY backend/src/voxlush/voxel/resources/legacy_render.py /runtime/legacy_render.py
ENV PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
USER 10001:10001
ENTRYPOINT ["python", "-I", "/runtime/sandbox_worker.py"]
