# План архитектуры и разработки скила `skill-forge`

> **Статус:** исторический проектный документ (ADR на момент первичной разработки). Актуальное устройство и файлы (`scripts/_spec.py`, `assets/report.html`, `scripts/check.py`, `tests/`) описаны в [`skills/skill-forge/SKILL.md`](../skills/skill-forge/SKILL.md) и [`skills/skill-forge/README.md`](../skills/skill-forge/README.md).

Этот документ фиксирует проект решения для собственного мета-скила **создания, оптимизации, аудита и тестирования скилов** (`skills/skill-forge`), спроектированного поверх опыта создания `figcraft-flatpak`, универсальной системы хуков (`scripts/skill-hook-router.py`, `scripts/sync-hooks.py`) и анализа `anthropics/skills/skill-creator`.

---

## 1. Зачем делать свой мета-скил вместо использования `skill-creator` как есть

`anthropics/skills/skill-creator` задаёт сильную методологию оценки качества, но в чистом виде плохо подходит под наш кросс-агентный стек и CLI-центричные скилы:

| Проблема `skill-creator` | Как решает `skill-forge` |
| --- | --- |
| **Монолит на 33.2 KB (485 строк, ~8 300 токенов)** с инструкциями под Claude.ai / Cowork | Компактный [SKILL.md](../skills/skill-forge/SKILL.md) (**≤ 150 строк / ≤ 1 500 токенов**) + `references/` по требованию |
| **Нет фазы исследования живого инструмента** до написания текста | Обязательный этап **Probe → Optimize → Measure** (CLI, песочница, латентность, объём вывода, грабли параметров) |
| **Нет бюджета токенов у самого скила** | Встроенный аудит `scripts/audit-skill.py` замеряет idle- и active-токены и предупреждает о раздувании |
| **Тюнинг триггеров сломан вне Claude Code** (`claude -p`, `.claude/commands/`) | Локальный тестер `scripts/test-triggers.py`: прогоняет `should_trigger` / `should_not_trigger` и `deny_shell` в Python, JS (`bun`/`node`) и через `skill-hook-router.py` |
| **Валидатор требует `PyYAML`** (не установлен в системе) | Все скрипты на **чистом stdlib Python 3** |
| **Не знает о вашем конвейере** | Нативная работа с `new-skill.sh`, `validate.py --strict`, `sync-to-manager.sh` и `hook-triggers.json` |

### Что именно заимствуем из `skill-creator`

1. **Короткое интервью до черновика:** цель, целевые среды/песочница, фразы запуска и пограничные запросы (*near-misses*), критерии готовности.
2. **Стиль инструкций «объясняй *почему*»:** избегать пустого капса `ALWAYS`/`NEVER` и переобучения под 2–3 частных примера.
3. **Вынос рутины в `scripts/`:** если агент на каждом шаге пишет однотипные обёртки, парсеры или цепочки команд — это должно жить в детерминированном скрипте.
4. **A/B-оценка (`with_skill` vs baseline) и слепое сравнение:** параллельные прогоны через сабагентов активной среды (без привязки к `claude -p`) + объективные проверки (`grading.json`) + статический HTML-отчёт.
5. **Отрицательные тесты (`should_not_trigger`):** проверять ложные срабатывания на смежных запросах (например, управление библиотекой через `manage-skills` vs создание нового скила).

---

## 2. Структура скила `skills/skill-forge/`

Скил не содержит зашитых абсолютных путей к `/home/zerg/Projects/skills`, чтобы корректно работать и из репозитория, и после деплоя в `~/.skills-manager/skills/skill-forge/`.

```text
skills/skill-forge/
├── SKILL.md                       # Основной алгоритм и жёсткие бюджеты (~110–145 строк)
├── hook-triggers.json             # Кросс-агентный триггер для skill-hook-router.py / OpenCode
├── references/
│   ├── authoring-guide.md         # Правила текста, оптимизация CLI/MCP, regex для хуков
│   └── eval-playbook.md           # Кросс-агентный A/B eval, слепое сравнение, HTML-отчёт
├── scripts/
│   ├── audit-skill.py             # Структурная проверка + токен-бюджет (stdlib Python 3)
│   ├── test-triggers.py           # Тест промпт-/shell-триггеров (Python + JS + live router)
│   └── eval-summary.py            # Агрегатор A/B grading/timing -> JSON, Markdown, HTML
└── evals/
    └── trigger-tests.json         # Набор положительных и near-miss тестов для самого skill-forge
```

### Целевой токен-бюджет

| Слой | Лимит | Назначение |
| --- | --- | --- |
| `SKILL.md` frontmatter (idle) | **≤ 150 токенов** | Всегда в контексте агента |
| `SKILL.md` целиком (active) | **≤ 1 500 токенов / ≤ 150 строк** | Подгружается только при вызове |
| `references/*.md` | **≤ 2 500 токенов** каждый | Подгружаются строго по задаче |
| `scripts/*.py` | **0 токенов** до чтения | Выполняются как CLI-инструменты |

---

## 3. Шестиэтапный цикл разработки скила

1. **Intake (Сбор требований):**
   - Уточнить, что скил делает, в какой среде работает (Flatpak/Docker/CLI/API/чистая методика), какие запросы должны его вызывать, а какие — **нет**.
   - Решить, нужны ли скрипты-обёртки, хук (`hook-triggers.json`) и A/B-прогон.
2. **Probe (Зондирование инструмента — обязательно для CLI/API-скилов):**
   - Проверить реальную версию, `--help`, ограничения песочницы (пути, сеть, шрифты, env), размер JSON/текста схем и справочников, реальную задержку команд.
   - Выявить точные имена параметров, которые вызывают откаты/ошибки (как `crossAlign` или 4-элементный `padding` в FigCraft).
3. **Architect (Проектирование и разбиение по слоям):**
   - Вынести детерминированную работу в `scripts/` (авто-монтирование путей, батчинг, сжатый `--compact` вывод, ограниченный поиск команд `lookup` вместо дампа).
   - Спроектировать `references/` для длинных таблиц команд/параметров.
   - Решить, нужен ли `hook-triggers.json` (промпт-подсказка и/или `deny_shell` от дорогих или ломающих команд).
4. **Author (Написание и скаффолдинг):**
   - Внутри skills-репозитория создать каркас через `scripts/new-skill.sh <name> [--with-scripts] [--with-references] [--with-hook]`.
   - Заполнить `SKILL.md` (императив, объяснение «почему», минимальный рабочий пример), `references/`, `scripts/` и `hook-triggers.json` (без inline-флагов вроде `(?i)` и без `\b` вокруг кириллицы).
5. **Test & Measure (Проверка и замер эффекта):**
   - `scripts/audit-skill.py --strict <skill-dir>` — проверить структуру и токен-бюджет.
   - `scripts/test-triggers.py <skill-dir> --live-router --js-check` — убедиться в 100% точности триггеров в Python и JS (`bun`/`node`).
   - Прогнать скрипты скила на живых данных и зафиксировать реальную экономию «до / после» (байты, токены, число шагов, миллисекунды).
   - При необходимости — провести кросс-агентный A/B eval (`references/eval-playbook.md` + `scripts/eval-summary.py`).
6. **Ship & Hook (Публикация в библиотеку):**
   - Из корня skills-репозитория прогнать `./scripts/validate.py --strict <name>`.
   - Проверить деплой с `--dry-run`, затем выполнить `./scripts/sync-to-manager.sh <name> --deploy ... --hooks --backup` и зафиксировать в Git.

---

## 4. Контракты встроенных скриптов

- **`audit-skill.py [--strict] [--json] <skill-dir>...`**
  - Проверяет frontmatter, `name` == имя папки, `kebab-case`, длину `description` (≤ 1024) и `compatibility` (≤ 500), отсутствие `<`/`>` и `TODO:`, отсутствие `.git`, executable-права у `scripts/*.sh|*.py`, корректность `hook-triggers.json` (включая предупреждение о кириллическом `\b` и inline-флагах).
  - Выводит таблицу метрик: байты и примерные токены для idle, active, `references/`, числа скриптов и статуса хуков.
- **`test-triggers.py [--test-file PATH] [--live-router] [--js-check] [--json] <skill-dir>`**
  - Читает `evals/trigger-tests.json` (`prompts: [{query, should_trigger}]`, `shell: [{command, should_deny}]`).
  - Проверяет совпадения в Python `re`, при `--js-check` (или автообнаружении `bun`/`node`) сверяет результат с JS `RegExp`, а при `--live-router` прогоняет через `scripts/skill-hook-router.py` (если он найден в дереве репозитория) для всех CLI-адаптеров.
- **`eval-summary.py <iteration-dir> [--skill-name NAME] [--html OUT.html]`**
  - Собирает `grading.json` и `timing.json` из подпапок `eval-*/{with_skill,without_skill,old_skill}`, считает среднее/СКО `pass_rate`, длительность, токены и дельту, записывает `benchmark.json`, `benchmark.md` и опционально автономный `report.html`.

---

## 5. План дальнейшего развития (после базовой реализации)

- При необходимости добавить **семантический тест `SKILL.md` description** через доступный локально CLI-агент (например, `codex` / `opencode`) как опциональную замену `claude -p`, если понадобится автоматически подбирать формулировки `description` без ручных хуков.
- Переиспользовать `audit-skill.py` как предкоммитную проверку для всех новых скилов в репозитории.
