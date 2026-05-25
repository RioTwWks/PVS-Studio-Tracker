> Skill: `@fix-parser` — see [.cursor/skills/fix-parser/SKILL.md](../skills/fix-parser/SKILL.md)

Парсер падает на отчёте PVS-Studio vX.Y.Z. Поля могут отличаться.
- Используй .get() с fallback'ами
- Логируй предупреждения при неизвестных ключах
- Не крашь весь запрос, помечай проблемные строки как skipped
- Обнови parser.py и добавь unit-тест в tests/test_parser.py
