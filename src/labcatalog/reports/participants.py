from collections.abc import Callable

from labcatalog.config import Vocab, WaveConfig
from labcatalog.project import Project
from labcatalog.reports import templates
from labcatalog.reports.measures import number, series
from labcatalog.reports.templates import Wording
from labcatalog.stats.summary import ModalityCount, Summary, WaveRetention, wave_order

KEY = "participants"


def wording_for(project: Project, study: str) -> Wording:
    own = next((c.participants for c in project.studies.values() if c.study == study), None)
    return templates.layered(project.config, KEY, own)


def paragraph(
    project: Project, summary: Summary, study: str, wording: Wording | None = None
) -> str:
    wording = wording or wording_for(project, study)
    values = placeholder_values(project, summary, study, wording)
    return wording.say(KEY, templates.PARAGRAPH, **values)


def placeholder_values(
    project: Project, summary: Summary, study: str, wording: Wording
) -> dict[str, str]:
    def say(slot: str, **values: object) -> str:
        return wording.say(KEY, slot, **values)

    config = project.config.studies[study]
    rows = [r for r in summary.retention if r.study == study]
    waves = sorted({r.wave for r in rows}, key=wave_order)
    described = []
    for wave in waves:
        dates = wave_dates(config.waves.get(wave, WaveConfig()))
        described.append(
            say("wave_dated", wave=wave, dates=dates) if dates else say("wave", wave=wave)
        )
    if len(waves) == 1:
        collected = say("waves_one", wave=described[0])
    else:
        collected = say("waves_many", n_waves=number(len(waves)), waves=series(described))
    groups = {g.wave: g for g in summary.groups if g.study == study}
    # With one reporter, naming it adds nothing ("30 self respondents").
    named = len({r.reporter for r in rows}) > 1
    return {
        "study": config.label or study,
        "n_waves": number(len(waves)),
        "waves": collected,
        "counts": " ".join(
            counts(
                wave,
                [r for r in rows if r.wave == wave],
                groups.get(wave),
                summary.group_name,
                named,
                say,
            )
            for wave in waves
        ),
        "demographics": " ".join(
            say("demographics", respondents=respondents(reporter, named))
            for reporter in dict.fromkeys(r.reporter for r in rows)
        ),
        "retention": " ".join(
            returned(waves[i - 1], wave, rows, named, say) for i, wave in enumerate(waves) if i
        ),
        "modalities": modalities(summary, study, project.config.vocab, named, say),
    }


def modality_rows(summary: Summary, study: str) -> list[tuple[str, str, list[ModalityCount]]]:
    # Each modality and reporter of a study with its waves in order; none when it has one modality.
    found = [m for m in summary.modalities if m.study == study]
    if len({m.modality for m in found}) < 2:
        return []
    return [
        (
            modality,
            reporter,
            sorted(
                (m for m in found if (m.modality, m.reporter) == (modality, reporter)),
                key=lambda m: wave_order(m.wave),
            ),
        )
        for modality, reporter in dict.fromkeys((m.modality, m.reporter) for m in found)
    ]


def wave_totals(summary: Summary, study: str) -> dict[tuple[str, str], int]:
    return {(r.wave, r.reporter): r.n for r in summary.retention if r.study == study}


def modalities(
    summary: Summary, study: str, vocab: Vocab, named: bool, say: Callable[..., str]
) -> str:
    totals = wave_totals(summary, study)
    sentences = []
    for modality, reporter, found in modality_rows(summary, study):
        # A modality everyone has at every wave adds nothing to the counts.
        if all(m.n == totals[(m.wave, reporter)] for m in found):
            continue
        parts = [
            say(
                "modality_each",
                n=number(m.n),
                total=number(totals[(m.wave, reporter)]),
                respondents=respondents(reporter, named) if i == 0 else "",
                wave=m.wave,
                share=share(m.n, totals[(m.wave, reporter)]),
            )
            for i, m in enumerate(found)
        ]
        label = vocab.modality_label(modality)
        sentences.append(say("modality", modality=label, counts=series(parts)))
        before = {m.wave: m.n for m in found}
        again = [
            say(
                "modality_again_each",
                n=number(m.n_from_previous),
                total=number(before[m.previous_wave]),
                previous=m.previous_wave,
                wave=m.wave,
                share=share(m.n_from_previous, before[m.previous_wave]),
            )
            for m in found
            if m.previous_wave is not None
        ]
        if again:
            sentences.append(say("modality_again", again=series(again)))
    return " ".join(sentences)


def respondents(reporter: str, named: bool) -> str:
    return f"{reporter} respondents" if named else "respondents"


def counted(n: int, reporter: str, named: bool) -> str:
    return f"{number(n)} {reporter}" if named else number(n)


def counts(
    wave: str,
    rows: list[WaveRetention],
    groups,
    group_name: str | None,
    named: bool,
    say: Callable[..., str],
) -> str:
    people = series([counted(r.n, r.reporter, named) for r in rows])
    if groups is not None and group_name:
        return say(
            "count_groups",
            wave=wave,
            respondents=people,
            n_groups=number(groups.groups),
            group=group_name,
            n_complete=number(groups.with_every_reporter),
        )
    return say("count", wave=wave, respondents=people)


def returned(
    previous: str, wave: str, rows: list[WaveRetention], named: bool, say: Callable[..., str]
) -> str:
    before = {r.reporter: r.n for r in rows if r.wave == previous}
    now = [r for r in rows if r.wave == wave and before.get(r.reporter)]
    if not now:
        return ""
    again = [
        say(
            "returned_each",
            n=number(r.n_from_previous),
            total=number(before[r.reporter]),
            respondents=respondents(r.reporter, named),
            percent=f"{round(100 * r.n_from_previous / before[r.reporter])}%",
        )
        for r in now
    ]
    new = series([counted(r.n_new, r.reporter, named) for r in now])
    return say("returned", wave=wave, previous=previous, again=series(again), new=new)


def share(n: int, total: int) -> str:
    # A wave whose files are still empty has no share to give.
    return f"({round(100 * n / total)}%)" if total else ""


def wave_dates(wave: WaveConfig) -> str:
    if wave.start and wave.end:
        return f"{wave.start} to {wave.end}"
    if wave.start:
        return f"since {wave.start}"
    if wave.end:
        return f"until {wave.end}"
    return ""
