from labcatalog.schema import Instrument

# Scores, references and a license belong to published questionnaires; a lab's demographics form
# and the measures of other modalities are judged on what they always need.
QUESTIONNAIRE = "questionnaire"


def gaps(instrument: Instrument) -> list[str]:
    present = {"items": bool(instrument.items)}
    if not instrument.demographics:
        present["construct"] = bool(instrument.construct_name)
        present["description"] = bool(instrument.description)
    if instrument.modality == QUESTIONNAIRE and not instrument.demographics:
        present["scores"] = bool(instrument.scores)
        present["reference"] = bool(instrument.references)
        present["reference PDF"] = any(r.pdf for r in instrument.references)
        present["license"] = bool(instrument.license)
    return [name for name, there in present.items() if not there]
