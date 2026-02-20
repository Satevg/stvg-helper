FROM public.ecr.aws/lambda/python:3.12

COPY pyproject.toml uv.lock ./
RUN pip install uv --quiet && \
    uv export --frozen --no-dev --no-emit-project | pip install -r /dev/stdin --quiet

COPY bot/ ${LAMBDA_TASK_ROOT}/
COPY models/ ${LAMBDA_TASK_ROOT}/models/

CMD ["handler.lambda_handler"]
