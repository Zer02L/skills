# Репозиторий для создания скилов

Локальный Git-репозиторий для разработки, валидации и синхронизации собственных агентских скилов с **Skills Manager** (`~/.skills-manager/bin/skills-manager-cli`).

## Структура

```text
.
├── skills/                     # Ваши скилы (по одной папке на скил)
│   └── <skill-name>/
│       ├── SKILL.md            # Обязательный файл инструкций с YAML frontmatter
│       ├── scripts/            # (опционально) Исполняемые скрипты
│       ├── references/         # (опционально) Справочные документы
│       └── assets/             # (опционально) Шаблоны, ассеты
├── templates/
│   └── skill-template/SKILL.md # Стартовый шаблон для новых скилов
├── scripts/
│   ├── new-skill.sh            # Создать заготовку нового скила
│   ├── validate.py             # Проверить формат, имена и ограничения
│   └── sync-to-manager.sh      # Провалидировать и синхронизировать со Skills Manager
├── AGENTS.md                   # Правила для AI-агентов в этом репозитории
└── CLAUDE.md -> AGENTS.md      # Симлинк для Claude Code
```

## Ежедневный цикл разработки

### 1. Создать заготовку нового скила

```bash
./scripts/new-skill.sh my-skill
# При необходимости сразу создать подпапки:
./scripts/new-skill.sh my-skill --with-scripts --with-references --with-assets
```

### 2. Написать `skills/my-skill/SKILL.md`

Опишите в YAML frontmatter `name` (должен совпадать с именем папки) и `description` (подробно укажите, что делает скил и в каких случаях он должен срабатывать; без `<` и `>`, до 1024 символов). Старайтесь держать `SKILL.md` короче 500 строк, а объёмные детали выносить в `references/`.

### 3. Проверить валидатором

```bash
./scripts/validate.py            # проверить все скилы в skills/
./scripts/validate.py --strict   # warnings (TODO: или >500 строк) тоже считаются ошибками
```

### 4. Синхронизировать со Skills Manager

```bash
# Предпросмотр без изменений
./scripts/sync-to-manager.sh --dry-run my-skill --deploy claude_code

# Установить/обновить в библиотеке Skills Manager и задеплоить агенту
./scripts/sync-to-manager.sh my-skill --deploy claude_code

# Обновить сразу все скилы, задеплоить нескольким агентам и запушить бэкап
./scripts/sync-to-manager.sh --all --deploy claude_code --deploy codex --backup
```

> **Важно:** редактируйте свои скилы только здесь (`skills/<name>/`). Не правьте их копии внутри `~/.skills-manager/skills/<name>/` — при следующем `sync-to-manager.sh` / `skills update` правки там будут перезаписаны.

## Какие ключи агентов доступны

Список всех установленных агентов и их ключей для `--deploy`:

```bash
~/.skills-manager/bin/skills-manager-cli agents list
```

Например: `claude_code`, `codex`, `gemini_cli`, `opencode`, `antigravity`, `deepseek_harness`.

## Публикация на GitHub в отдельный репозиторий (по желанию)

Бэкап-репозиторий `skills-manager-backup` хранит всю вашу библиотеку вместе со сторонними скилами и метаданными. Если позже захотите выложить **только свои скилы** в отдельный публичный или приватный репозиторий на GitHub:

1. Создайте репозиторий и отправьте туда код:
   ```bash
   gh repo create skills --private --source=. --remote=origin --push
   ```
2. Переключите источник скила в Skills Manager на GitHub (теги, пресеты и деплои сохранятся):
   ```bash
   ~/.skills-manager/bin/skills-manager-cli skills set-source my-skill \
     --git-url https://github.com/<ваш-логин>/skills/tree/main/skills/my-skill
   ```
После этого обновления скила можно будет подтягивать из GitHub командой `skills update my-skill` (после `git push`).
