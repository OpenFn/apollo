FROM python:3.11-bullseye

WORKDIR /app

RUN apt-get update && apt-get install -y git

RUN git init /app/repo
WORKDIR /app/repo
RUN git remote add origin https://github.com/OpenFn/docs.git
RUN git config core.sparseCheckout true
RUN echo "docs/*" >> .git/info/sparse-checkout
RUN git pull origin main

WORKDIR /app

COPY ./pyproject.toml ./poetry.lock poetry.toml ./
COPY ./package.json bun.lockb ./
COPY ./tsconfig.json ./
COPY ./init_milvus.py ./

COPY ./platform/ ./platform
COPY ./services/ ./services
COPY ./models/ ./models

RUN python -m pip install --user pipx
RUN python -m pipx install poetry
ENV PATH="${PATH}:/root/.local/bin/"
RUN poetry install --only main --no-root

RUN curl -fsSL https://bun.sh/install | bash
ENV PATH="${PATH}:/root/.bun/bin/"

RUN bun install

RUN --mount=type=secret,id=_env,dst=/.env cat /.env \
    && poetry run python init_milvus.py

EXPOSE 3000

CMD ["bun", "start"]
