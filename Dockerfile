FROM python:3.11-bullseye

WORKDIR /app

COPY ./pyproject.toml ./poetry.lock poetry.toml ./
COPY ./package.json bun.lockb ./
COPY ./tsconfig.json ./

COPY ./platform/ ./platform
COPY ./services/ ./services
COPY ./models/ ./models

RUN apt-get update && apt-get install -y git
RUN git clone --depth 1 https://github.com/OpenFn/docs.git /app/docs

RUN python -m pip install --user pipx
RUN python -m pipx install poetry
ENV PATH="${PATH}:/root/.local/bin/"
RUN poetry install --only main --no-root

RUN curl -fsSL https://bun.sh/install | bash
ENV PATH="${PATH}:/root/.bun/bin/"

RUN bun install

RUN --mount=type=secret,id=_env,dst=/.env cat /.env \
    && poetry run python services/search/generate_docs_embeddings.py docs openfn_docs_jobs

EXPOSE 3000

CMD ["bun", "start"]
