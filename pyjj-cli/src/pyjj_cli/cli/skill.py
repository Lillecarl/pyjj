def add_parsers(sub) -> None:
    p_skill = sub.add_parser(
        "skill", help="Work with the bundled agent skill")
    p_skill.set_defaults(_handler="pyjj_cli.commands.skill:skill_path",
                         name="pyjj")
    skill_sub = p_skill.add_subparsers(dest="skill_command")

    p_path = skill_sub.add_parser(
        "path", help="Print the installed SKILL.md path")
    p_path.add_argument("name", nargs="?", default="pyjj",
                        help="Skill to locate (default: pyjj)")
    p_path.set_defaults(_handler="pyjj_cli.commands.skill:skill_path")
