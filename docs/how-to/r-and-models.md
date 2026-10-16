# Set Up R and Language Models

labcatalog runs without R and without a language model. R adds factor models and lets every analysis run in R; a language model drafts instruments and scoring scripts. Both are settings of your computer, made on the **Settings** page, and labcatalog never installs either for you.

## R and the packages it needs

With R, labcatalog runs every analysis in R first and in Python only when R is not set or fails. Confirmatory factor analysis and ω also have a Python version, but measurement invariance across waves needs R.

1. Install R from [CRAN](https://cran.r-project.org/).
2. In R, install the packages labcatalog uses:

   ```r
   install.packages(c("lavaan", "semTools", "psych", "effectsize", "MBESS", "lme4", "lmerTest", "performance"))
   ```

3. On the **Settings** page, under **R**, give the path to `Rscript`, which is in R's `bin` folder, for example `C:\Program Files\R\R-4.5.2\bin\Rscript.exe` on Windows or `/usr/local/bin/Rscript` on macOS and Linux.
4. Press **Save and check**. labcatalog runs R once and reports its version and any packages that are missing, with the command to install them.

Every analysis shows whether it was computed in R or in Python, and its **Code** section has both versions.

## Language models

A language model can:

- draft an instrument file, scores included, from the instrument's PDF (the Edit page);
- draft the description for the Measures paragraph and write scoring scripts from the reference PDF (an instrument's page);
- find items by what they ask about (the Instruments page).

What it writes is always a draft for you to check, and the references, license and tags are always filled in by hand. These features need the `ai` extra (see [Installation](../getting-started/installation.md)).

On the **Settings** page, under **Language model**, choose the provider and the model, and press **Save**.

- **Anthropic, OpenAI or Gemini**: labcatalog reads the API key from an environment variable, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` or `GEMINI_API_KEY`, and never stores it. Set it yourself and restart labcatalog. On Windows: `setx ANTHROPIC_API_KEY your-key` in a terminal. On macOS or Linux, add `export ANTHROPIC_API_KEY=your-key` to your shell profile. The page says whether the variable is set.
- **Local (OpenAI-compatible server)**: a model running on your own computer or server, for example with Ollama or LM Studio. Give the server's address, for example `http://localhost:11434/v1`. Nothing leaves your network.

With a cloud provider, the text you send (a PDF's text, item wording) goes to that provider. Do not send anything your data agreements do not allow.
