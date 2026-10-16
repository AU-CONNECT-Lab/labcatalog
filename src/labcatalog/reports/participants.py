from labcatalog.config import WaveConfig
from labcatalog.measures import number, series
from labcatalog.project import Project
from labcatalog.stats.summary import Summary, WaveRetention, wave_order

DEFAULT_TEMPLATE = "{waves} {counts} {retention}"
PLACEHOLDERS = ("study", "n_waves", "waves", "counts", "retention")


def template_for(project: Project, study: str) -> str:
    own = [c.participants for c in project.studies.values() if c.study == study and c.participants]
    return next(iter(own), None) or project.config.participants or DEFAULT_TEMPLATE


def paragraph(project: Project, summary: Summary, study: str) -> str:
    values = placeholder_values(project, summary, study)
    return " ".join(template_for(project, study).format_map(values).split())


def placeholder_values(project: Project, summary: Summary, study: str) -> dict[str, str]:
    config = project.config.studies[study]
    rows = [r for r in summary.retention if r.study == study]
    waves = sorted({r.wave for r in rows}, key=wave_order)
    described = []
    for wave in waves:
        dates = wave_dates(config.waves.get(wave, WaveConfig()))
        described.append(f"Wave {wave}" + (f" ({dates})" if dates else ""))
    if len(waves) == 1:
        collected = f"Data were collected in {described[0]}."
    else:
        collected = f"Data were collected in {number(len(waves))} waves: {series(described)}."
    groups = {g.wave: g for g in summary.groups if g.study == study}
    return {
        "study": config.label or study,
        "n_waves": number(len(waves)),
        "waves": collected,
        "counts": " ".join(
            counts(wave, [r for r in rows if r.wave == wave], groups.get(wave), summary.group_name)
            for wave in waves
        ),
        "retention": " ".join(
            returned(waves[i - 1], wave, rows) for i, wave in enumerate(waves) if i
        ),
    }


def counts(wave: str, rows: list[WaveRetention], groups, group_name: str | None) -> str:
    text = f"At Wave {wave}, {series([f'{number(r.n)} {r.reporter}' for r in rows])} respondents"
    if groups is not None and group_name:
        text += (
            f" from {number(groups.groups)} {group_name} groups "
            f"({number(groups.with_every_reporter)} with every reporter)"
        )
    return f"{text} took part."


def returned(previous: str, wave: str, rows: list[WaveRetention]) -> str:
    before = {r.reporter: r.n for r in rows if r.wave == previous}
    now = [r for r in rows if r.wave == wave and before.get(r.reporter)]
    if not now:
        return ""
    again = [
        f"{number(r.n_from_previous)} of {number(before[r.reporter])} {r.reporter} respondents "
        f"({round(100 * r.n_from_previous / before[r.reporter])}%)"
        for r in now
    ]
    new = [f"{number(r.n_new)} {r.reporter}" for r in now]
    return (
        f"At Wave {wave}, {series(again)} from Wave {previous} took part again; "
        f"{series(new)} respondents were new."
    )


def wave_dates(wave: WaveConfig) -> str:
    if wave.start and wave.end:
        return f"{wave.start} to {wave.end}"
    if wave.start:
        return f"since {wave.start}"
    if wave.end:
        return f"until {wave.end}"
    return ""
