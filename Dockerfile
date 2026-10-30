ARG NODE_VERSION=26.13.0

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

# Mozilla distrusted emSign C1 and C3 (eMudhra intermediates with weak keys).
# This fails once Debian's ca-certificates drops them, so the step can go.
RUN for cert in emSign_Root_CA_-_C1 emSign_ECC_Root_CA_-_C3; do \
      grep -qx "mozilla/${cert}.crt" /etc/ca-certificates.conf \
        || { echo "${cert} is no longer shipped; remove this step" >&2; exit 1; }; \
      sed -i "s|^mozilla/${cert}.crt\$|!mozilla/${cert}.crt|" /etc/ca-certificates.conf; \
    done \
  && update-ca-certificates --fresh

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
