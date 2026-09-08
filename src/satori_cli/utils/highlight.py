from rich.highlighter import RegexHighlighter
from rich.text import Text
from rich.theme import Theme


class SatoriHighlighter(RegexHighlighter):
    base_style = "satori."
    highlights = [
        r"(?P<value>(?<=:\s)\w+$)",
        r"(?P<email>[\w-]+@([\w-]+\.)+[\w-]+)",
        r"(?P<pass>((^|(:|>) )(p|P)ass|(c|C)ompleted|(f|F)inished|(t|T)rue)($|\s))",
        r"(?P<pending>((^|: )(p|P)ending|(q|Q)ueued|(r|R)unning)($|\s))",
        r"(?P<fail>((^|(:|>) )(f|F)ail(\(\d+\))?|(e|E)rror|(f|F)alse)($|\s))",
        r"(?P<unknown>((^|: )(u|U)nknown|undefined|null|None|N/A|(S|s)topped|(C|c)ancell?ed)($|\s))",
        r"(?P<satori_com>https?:\/\/(www\.)?(dashboard\.)?satori(-ci)?\.(com|ci)\S*)",
        r"(?P<satori_uri>(satori|bundle):\/\/\S+)",
        r"(?P<key>([^\w]|^)\w[\w\s]*:\s*)(?!\/\/)",
        r"(?P<number>(?<!\w)\-?[0-9]+\.?[0-9]*(e[-+]?\d+?)?\b|0x[0-9a-fA-F]*)",
        r"(?P<uuid>[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12})",
        r"(?P<testcase_pass>\w+ > [^:]+: Pass$)",
        r"(?P<testcase_fail>\w+ > [^:]+: Fail$)",
        r"(?P<db_date>\d{4}-\d?\d-\d?\d(\w|\s)\d{2}:\d{2}:\d{2})",
        r"(?P<id>(r|m|p|s)\w{15}$)",
        r"(?P<yes>^Yes$)",
        r"(?P<no>^No$)",
    ]


SATORI_STYLES = {
    "debug": "dim blue",
    "info": "dim cyan",
    "warning": "yellow",
    "danger": "bold red",
    "error": "red",
    "critical": "on red",
    "multiline": "yellow",
    "satori.email": "cyan",
    "satori.pass": "chartreuse1",
    "satori.pending": "dark_slate_gray3",
    "satori.fail": "bright_red",
    "satori.unknown": "bright_yellow",
    "satori.satori_com": "turquoise2",
    "satori.satori_uri": "dark_turquoise",
    "satori.key": "white b",
    "satori.value": "cyan1",
    "satori.number": "deep_sky_blue1",
    "satori.uuid": "purple",
    "satori.testcase_pass": "green",
    "satori.testcase_fail": "red",
    "satori.db_date": "bright_magenta",
    "satori.id": "dark_slate_gray2",
    "satori.no": "chartreuse1",
    "satori.yes": "bright_red",
}

satori_theme = Theme(SATORI_STYLES)

_highlighter = SatoriHighlighter()


def highlight_text(text: str) -> Text:
    """Apply SatoriHighlighter (needed for Table cells, which skip Console highlight)."""
    return _highlighter(Text(text))


def highlight_result(text: str) -> Text:
    """Apply theme Pass/Fail styles when console highlighting is not enough."""
    return highlight_text(text)
