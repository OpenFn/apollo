FROM python:3.11-bullseye

WORKDIR /app

COPY ./pyproject.toml ./poetry.lock poetry.toml ./
COPY ./package.json bun.lockb ./
COPY ./tsconfig.json ./

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

EXPOSE 3000

CMD ["bun", "start"]
