# Репозиторий для создания скилов

Локальный Git-репозиторий ([`Zer02L/skills`](https://github.com/Zer02L/skills)) для разработки, валидации, тестирования и синхронизации собственных агентских скилов со **Skills Manager** (`~/.skills-manager/bin/skills-manager-cli`).

## Каталог скилов

| Скил | Назначение | Скрипты | Авто-хук |
| --- | --- | --- | --- |
| [`bottleneck-audit`](skills/bottleneck-audit) | Диагностика узких мест (CPU, DB/SQL, I/O, память, бандл/CI) по закону Амдала | `scan-hotspots.py`, `bench-cmd.py` | `enabled` |
| [`figcraft-flatpak`](skills/figcraft-flatpak) | Работа с `.figcraft`/`.fig`/`.penpot`/`.sketch` через Flatpak FigCraft без расхода токенов на дамп команд | `fc.sh` | `enabled` (`deny_shell=2`) |
| [`skill-forge`](skills/skill-forge) | Мета-скил для проектирования, аудита токен-бюджетов и A/B-бенчмаркинга скилов | `audit-skill.py`, `test-triggers.py`, `eval-summary.py` | `enabled` |

## Структура

```text
.
├── .github/workflows/ci.yml        # CI-проверка качества на push/PR
├── skills/                         # Автономные скилы (по одной папке на скил)
│   └── <skill-name>/
│       ├── SKILL.md                # Обязательный манифест с YAML frontmatter
│       ├── hook-triggers.json      # (опционально) Правила авто-хуков и deny_shell
│       ├── evals/                  # (опционально) Наборы trigger-tests.json
│       ├── scripts/                # (опционально) Исполняемые скрипты и _*.py-модули
│       ├── references/             # (опционально) Справочники по требованию
│       └── assets/                 # (опционально) Шаблоны и ассеты
├── templates/
│   └── skill-template/
│       ├── SKILL.md                # Стартовый шаблон для новых скилов
│       ├── hook-triggers.json      # Шаблон правил авто-хука (--with-hook)
│       └── evals/trigger-tests.json
├── scripts/
│   ├── check.py                    # Единый прогон: py_compile, validate, audit, triggers, unittest
│   ├── new-skill.sh                # Создать заготовку нового скила (обёртка -> lib/scaffold.py)
│   ├── validate.py                 # Проверить формат, имена, хуки и ограничения
│   ├── sync-to-manager.sh          # Синхронизация со Skills Manager (обёртка -> lib/manager.py)
│   ├── skill-hook-router.py        # Единый роутер хуков для всех CLI-агентов
│   ├── sync-hooks.py               # Идемпотентный установщик хуков + OpenCode-плагин
│   └── lib/                        # Внутренняя библиотека только для корневых скриптов
├── tests/                          # Автотесты (stdlib unittest)
├── AGENTS.md                       # Правила для AI-агентов в этом репозитории
└── CLAUDE.md -> AGENTS.md          # Симлинк для Claude Code
```

## Ежедневный цикл разработки

### 1. Создать заготовку нового скила

```bash
./scripts/new-skill.sh my-skill
# При необходимости сразу создать подпапки, авто-хук и заготовку evals/trigger-tests.json:
./scripts/new-skill.sh my-skill --with-scripts --with-references --with-assets --with-hook
```

### 2. Написать `skills/my-skill/SKILL.md`

Опишите в YAML frontmatter `name` (должен совпадать с именем папки) и `description` (подробно укажите, что делает скил и в каких случаях он должен срабатывать; без `<` и `>`, до 1024 символов). Держите `SKILL.md` компактным (ориентир из `skill-forge`: `<= 150` строк / `<= 1 500` токенов; жёсткое предупреждение на 500 строках), а объёмные детали выносите в `references/`.

### 3. Проверить качество и тесты

```bash
./scripts/check.py --require-js  # полная проверка: compile + validate --strict + audit --strict + triggers + unittest
./scripts/validate.py --strict   # только строгая валидация структуры и хуков
```

### 4. Синхронизировать со Skills Manager

```bash
# Предпросмотр без изменений
./scripts/sync-to-manager.sh --dry-run my-skill --deploy claude_code

# Установить/обновить в библиотеке Skills Manager и задеплоить агенту
./scripts/sync-to-manager.sh my-skill --deploy claude_code

# Обновить сразу все скилы, задеплоить нескольким агентам, обновить хуки и запушить бэкап
./scripts/sync-to-manager.sh --all --deploy claude_code --deploy codex --hooks --backup
```

> **Важно:** редактируйте свои скилы только здесь (`skills/<name>/`). Не правьте их копии внутри `~/.skills-manager/skills/<name>/` — при следующем `sync-to-manager.sh` / `skills update` правки там будут перезаписаны.

## Мета-скил разработки скилов (`skill-forge`)

Для создания, оптимизации и аудита скилов в репозитории доступен собственный мета-скил [skills/skill-forge](skills/skill-forge).

Подробное сравнение `skill-forge` с эталонными аналогами от Anthropic и OpenAI (`skill-creator`), разбор архитектурных преимуществ, компромиссов и токен-бюджетов вынесены в [skills/skill-forge/README.md](skills/skill-forge/README.md).

## Универсальные хуки для автосрабатывания (`hook-triggers.json`)

Если для скила нужно гарантированное срабатывание на промпт или блокировка неправильных CLI-команд, добавьте рядом с `SKILL.md` файл `hook-triggers.json` и тесты `evals/trigger-tests.json` (создаются автоматически через `--with-hook` в `new-skill.sh`).

- Проверить статус правил и агентов:
  ```bash
  ./scripts/sync-hooks.py --status
  ```
- Установить/обновить роутер во всех обнаруженных агентах (`antigravity`, `codex`, `claude_code`, `gemini_cli`, `opencode`):
  ```bash
  ./scripts/sync-hooks.py --dry-run   # предпросмотр
  ./scripts/sync-hooks.py             # установка (существующие хуки сохраняются)
  ./scripts/sync-hooks.py --uninstall # удалить только custom-skills-router
  ```
- Временно обойти shell-блокировку можно переменной окружения `SKIP_SKILL_HOOKS=1`.
- Агенты без нативного API хуков (`deepseek_harness`, `omp_agent`, `command_code`, `pi`) срабатывают через поле `description` в `SKILL.md`.

## Какие ключи агентов доступны

Список всех установленных агентов и их ключей для `--deploy`:

```bash
~/.skills-manager/bin/skills-manager-cli agents list
```

Например: `claude_code`, `codex`, `gemini_cli`, `opencode`, `antigravity`, `deepseek_harness`.

## Отслеживание скила напрямую из GitHub (по желанию)

Репозиторий уже размещён в [`Zer02L/skills`](https://github.com/Zer02L/skills). Если захотите переключить источник конкретного скила в Skills Manager с локальной папки на GitHub (сохранив теги, пресеты и деплои):

```bash
~/.skills-manager/bin/skills-manager-cli skills set-source my-skill \
  --git-url https://github.com/Zer02L/skills/tree/main/skills/my-skill
```

После этого обновления скила можно будет подтягивать из GitHub командой `skills update my-skill` (после `git push`).
