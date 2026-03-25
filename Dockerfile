FROM public.ecr.aws/lambda/python:3.12

WORKDIR ${LAMBDA_TASK_ROOT}

COPY pyproject.toml uv.lock ./
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN pip install --no-cache-dir --quiet uv==0.10.2 && \
    uv export --frozen --no-dev --no-emit-project | pip install --no-cache-dir -r /dev/stdin --quiet

COPY bot/ ${LAMBDA_TASK_ROOT}/
COPY models/ ${LAMBDA_TASK_ROOT}/models/

CMD ["handler.lambda_handler"]
