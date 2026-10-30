FROM python:3.11-bookworm

WORKDIR /app

COPY ./pyproject.toml ./poetry.lock ./
COPY ./package.json bun.lock ./
COPY ./.tool-versions ./
COPY ./tsconfig.json ./
COPY ./path.config ./

COPY ./platform/ ./platform
COPY ./migrations/ ./migrations
COPY ./services/ ./services

RUN apt-get update && apt-get install -y git curl
RUN apt-get install -y --only-upgrade ca-certificates

RUN curl -fsSL https://deb.nodesource.com/setup_26.x | bash - \
    && apt-get install -y nodejs
RUN git clone --depth 1 https://github.com/OpenFn/docs.git /app/docs

RUN python -m pip install --user pipx
RUN python -m pipx install poetry
ENV PATH="${PATH}:/root/.local/bin/"
RUN poetry install --only main --no-root

RUN BUN_VERSION="$(awk '/^bun / {print $2}' .tool-versions)" \
    && curl -fsSL https://bun.sh/install | bash -s "bun-v${BUN_VERSION}"
ENV PATH="${PATH}:/root/.bun/bin/"

RUN bun install

EXPOSE 3000

CMD ["bun", "start"]
