ARG NODE_VERSION=26.12.0

FROM node:${NODE_VERSION}-bookworm-slim AS node

FROM python:3.11-bookworm

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

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
RUN test "v$(awk '/^nodejs / {print $2}' .tool-versions)" = "$(node -v)"
RUN git clone --depth 1 https://github.com/OpenFn/docs.git /app/docs

RUN python -m pip install --user pipx
RUN python -m pipx install poetry
ENV PATH="${PATH}:/root/.local/bin/"
RUN poetry install --only main --no-root

RUN BUN_VERSION="$(awk '/^bun / {print $2}' .tool-versions)" \
    && curl -fsSL https://bun.sh/install | bash -s "bun-v${BUN_VERSION}"
ENV PATH="${PATH}:/root/.bun/bin/"

RUN bun install

# RUN --mount=type=secret,id=_env,dst=/.env cat /.env \
#     && poetry run python services/search/generate_docs_embeddings.py docs openfn_docs

EXPOSE 3000

CMD ["bun", "start"]
