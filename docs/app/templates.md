# Templates

The Templates page holds the wording of the paragraphs labcatalog writes. Each paragraph comes from a template: text with placeholders in braces, such as `{counts}` or `{alpha}`, that the numbers fill in. The templates are listed on the left, grouped by the part of a paper they belong to; click one to open it. A **Wording** button beside a paragraph on the [Methods](methods.md) page or an instrument's page opens its template here.

## Editing a template

- **For**: whose wording it is. **The project** is the wording every study or instrument uses. The Participants template can also be set for one study and the Measures template for one instrument, in place of the project's; the Results templates are the project's only. A line under it says whether the wording shown is the built-in one, the project's, or the study's or instrument's own.
- The box holds the template. A Results template has a box for each sentence it can write, labelled with when that sentence is used, such as a correlation that is significant and one that is not. The placeholders it can use are listed under it; click one to put it where the cursor is. Write a literal brace as `{{` or `}}`.
- **Save** writes the template. **Reset** puts back the wording it falls back to (the built-in one for the project, the project's for a study or instrument); press **Save** to keep it. Wording that is the same as what it falls back to is not written to any file.
- Under each box, a preview writes the text as you type. For the Methods templates it comes from the project's data: the Participants paragraph for the chosen study (or the first one), the Measures paragraph for the chosen instrument (or the first one given in a dataset), without ω, which needs the factor models. For the Results templates it uses made-up numbers. A placeholder the box cannot use shows as an error in its place.

Choosing another template, or another **For**, with unsaved changes asks first.

## Where templates are kept

The project's templates are written under `templates` in `labcatalog.yaml`, a study's own Participants template to `participants` in its study file, and an instrument's own Measures template to `measures` in its instrument file:

```yaml
templates:
  participants: |
    {waves} {counts} {retention}
  measures: |
    We used {named}. {description} {items} {scoring} {alpha} {omega}
  regression:
    predictor: |
      {predictor} predicted {outcome}, {statistics}.
```

A Results template names each sentence it changes; the others keep the built-in wording.

| Template | Placeholders |
|---|---|
| `participants` | `study`, `n_waves`, `waves`, `counts`, `demographics`, `retention`, `modalities` |
| `measures` | `name`, `abbreviation`, `cite`, `named`, `construct`, `reporter`, `n_items`, `scale`, `description`, `items`, `reverse`, `scoring`, `alpha`, `omega` |
| `correlation` | `pair`, `pair_ns` and `listed`: `a`, `b`, `direction`, `statistic`, `r`, `p`; `count`: `n_pairs`, `n_significant`, `verb`; `strongest`: `n_shown`, `pairs`; `between` and `between_one`: `pairs`; `within`: none |
| `regression` | `predictor` and `predictor_ns`: `predictor`, `outcome`, `statistics`, `b`, `se`, `p`, `r2`, `n`; `intro`: none |
| `missing` | `all`: `people`, `variables`; `complete`: `people`, `complete`, `percent`, `which`; `each`: `missing`, `percent`; `range`: `low`, `low_percent`, `low_label`, `high`, `high_percent`, `high_label` |
| `groups` | `two`, `two_ns`, `more` and `more_ns`: `outcome`, `groups`, `statistics`, `test`, `p`, `effect`; `group`: `label`, `statistics`, `m`, `sd` |
| `agreement` | `icc`: `among`, `n`, `whom`, `single`, `mean`; `kappa`: `among`, `n`, `kappa`; `kappa_weighted`: those and `weighted`; `light`: `n_pairs`, `raters`, `light`, `low`, `high`; `studies`: `name`, `values`; `study`: `value`, `study` |

In the Results templates, a statistic placeholder holds the symbol and the value as APA writes them (`r(118) = .32`, `p < .001`); `statistic` and `statistics` hold them all, in order. `verb` is "was" or "were" to agree with the count.

See [Write the Methods Section](../how-to/write-methods.md) for what each Methods placeholder writes. `labcatalog validate` reports a template it does not know and a placeholder a template cannot use.
