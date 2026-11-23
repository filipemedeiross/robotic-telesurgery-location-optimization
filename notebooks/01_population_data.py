import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # MUNICIPAL POPULATION (2022 CENSUS)
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    Retrieve resident population from [IBGE SIDRA table 9514](https://sidra.ibge.gov.br/tabela/9514), variable 93, for men and women in 21 non-overlapping age groups.

    > **Note**.: The reference period is always 2022.
    """)
    return


@app.cell
def _():
    import json
    import time
    import hashlib
    import tempfile

    from pathlib        import Path
    from urllib.error   import URLError
    from http  .client  import HTTPException
    from types          import SimpleNamespace
    from urllib.request import Request  , urlopen
    from contextlib     import ExitStack, contextmanager

    import pandas as pd
    import marimo as mo

    return (
        ExitStack,
        HTTPException,
        Path,
        Request,
        SimpleNamespace,
        URLError,
        contextmanager,
        hashlib,
        json,
        mo,
        pd,
        tempfile,
        time,
        urlopen,
    )


@app.cell
def _(Path, SimpleNamespace):
    config = SimpleNamespace(
        root=Path(__file__).resolve().parents[1],

        api     ="https://apisidra.ibge.gov.br",
        table   ="9514",
        variable="93"  ,

        year ="2022"    ,
        sexes=("4", "5"),
        ages =(
            "93070", "93084", "93085", "93086", "93087", "93088", "93089",
            "93090", "93091", "93092", "93093", "93094", "93095", "93096",
            "93097", "93098", "49108", "49109", "60040", "60041", "6653" ,
        ),

        sex_total        ="6794"  ,
        age_total        ="100362",
        declaration_total="113635",

        safe_value_limit=45_000,
        timeout         =90    ,
    )

    config.cache = config.root / ".cache" / "ibge"
    return (config,)


@app.cell
def _(Path, contextmanager, tempfile):
    def require(condition, message):
        if not condition:
            raise ValueError(message)


    @contextmanager
    def staged_path(destination):
        """Stage a file beside its destination and always clean up the temporary"""

        destination.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.NamedTemporaryFile(
            dir   =destination.parent     ,
            prefix=f".{destination.name}.",

            suffix=".tmp",
            delete=False ,
        ) as temporary:
            path = Path(temporary.name)

        try:
            yield path
        finally:
            path.unlink(missing_ok=True)

    return require, staged_path


@app.cell
def _(
    HTTPException,
    Request,
    URLError,
    config,
    hashlib,
    json,
    require,
    staged_path,
    time,
    urlopen,
):
    def fetch_json(url):
        """Reuse query-specific JSON, or retrieve it with bounded retries"""

        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()

        cache_path = config .cache / f"{digest}.json"

        if cache_path.exists():
            try:
                payload = json.loads(
                    cache_path.read_text(encoding="utf-8-sig")
                )
            except (OSError, UnicodeError, ValueError) as error:
                print(f"Invalid cache; downloading again: {cache_path} ({error})")
            else:
                print(f"Cache: {url}")

                return payload

        for attempt in range(3):
            try:
                print(f"Downloading (attempt {attempt + 1}/3): {url}", flush=True)

                request = Request(
                    url,

                    headers={
                        "Accept" : "application/json",
                    }
                )

                with urlopen(request, timeout=config.timeout) as response:
                    body = response.read()

                payload = json.loads(body.decode("utf-8-sig"))

                require(    isinstance(payload, (dict, list)) and                 payload, "Empty or malformed JSON.")
                require(not isinstance(payload,  dict       ) or "Message" not in payload, str(payload)              )

            except (URLError, HTTPException, OSError, UnicodeError, ValueError) as error:
                if attempt == 2:
                    raise RuntimeError(f"IBGE request failed: {url}: {error}") from error

                time.sleep(2 ** attempt)
            else:
                with staged_path(cache_path) as temporary:
                    temporary.write_bytes(body      )
                    temporary.replace    (cache_path)

                return payload

    return (fetch_json,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## LOAD OFFICIAL CATEGORY LABELS
    """)
    return


@app.cell
def _(config, fetch_json):
    descriptor_url = f"{config.api}/DescritoresTabela/t/{config.table}"

    _descriptor = fetch_json(descriptor_url)

    classifications = {
        str(c["Id"]) : c
        for c in _descriptor["Classificacoes"]
    }
    category_labels = {
        code : {
            str(c["Id"]) : c["Nome"]
            for c in classification["Categorias"]
        }
        for code, classification in classifications.items()
    }
    return category_labels, classifications, descriptor_url


@app.cell
def _(config, fetch_json, pd, require):
    def query_url(level, sexes, ages):
        territory = "all" if level == "6" else "1"

        return (
            f"{config.api}/values/t/{config.table}/n{level}/{territory}"
            f"/v/{config.variable}/p/{config.year}/c2/{','.join(sexes)}"
            f"/c287/{','.join(ages)}/c286/{config.declaration_total}/h/y"
        )

    def read_sidra(url, level, sexes, ages):
        """Check query dimensions and parse nonnegative integer populations"""

        payload = fetch_json(url)

        require(
            isinstance(payload, list) and len(payload) > 1, f"No SIDRA records: {url}"
        )

        frame = pd.DataFrame(payload[1:], dtype="string")[
            [
                "NC" ,
                "D1C",
                "D2C",
                "D3C",
                "D4C",
                "D5C",
                "D6C",
                "V"  ,
            ]
        ].apply(lambda column: column.str.strip())

        expected = {
            "NC"  : level,
            "D2C" : config.variable         ,
            "D3C" : config.year             ,
            "D6C" : config.declaration_total,
        }

        require(
            all(
                frame[column].eq(value).fillna(False).all()
                for column, value in expected.items()
            )
            and set(frame["D4C"]) == set(sexes)
            and set(frame["D5C"]) == set(ages ),

            "Unexpected SIDRA period or dimensions.",
        )

        values  = frame["V"] .replace  ("-", "0" )
        invalid = ~values.str.fullmatch(r"[0-9]+", na=False)

        require(
            not invalid.any(), f"Invalid population values: {frame.loc[invalid, 'V'].unique().tolist()}"
        )

        frame["V"] = pd.to_numeric(values, errors="raise").astype("Int64")

        return frame

    return query_url, read_sidra


@app.cell
def _(pd):
    def municipal_frame(raw):
        return pd.DataFrame({
            "ibge_municipality_code" : raw["D1C"],
            "sex_code"               : raw["D4C"],
            "age_group_code"         : raw["D5C"],
            "resident_population"    : raw["V"  ],
        })

    return (municipal_frame,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## RETRIEVE CENSUS COVERAGE AND CONTROLS
    """)
    return


@app.cell
def _(config, municipal_frame, query_url, read_sidra, require):
    _url = query_url("6", (config.sex_total,), (config.age_total,))

    municipal_totals = municipal_frame(
        read_sidra(
            _url, "6", (config.sex_total,), (config.age_total,)
        )
    )

    require(municipal_totals["ibge_municipality_code"].is_unique, "Duplicate Census territory codes.")

    batch_size = config.safe_value_limit // (len(municipal_totals) * len(config.sexes))

    require(batch_size >= 1, "A single age group exceeds the SIDRA request limit.")

    age_batches = [config.ages[i:i + batch_size]      for i    in range(0, len(config.ages), batch_size)]
    batch_urls  = [query_url("6", config.sexes, ages) for ages in age_batches                           ]
    return age_batches, batch_urls, municipal_totals


@app.cell
def _(age_batches, batch_urls, config, municipal_frame, pd, read_sidra):
    _frames = []

    for _index, (_ages, _url) in enumerate(zip(age_batches, batch_urls, strict=True), 1):
        _frames.append(read_sidra(_url, "6", config.sexes, _ages))

        print(f"Batch {_index}/{len(age_batches)}: {len(_frames[-1]):,} records")

    population = municipal_frame(pd.concat(_frames, ignore_index=True))

    _age_order = {
        code : order
        for order, code in enumerate(config.ages)
    }

    population = population.sort_values(
        [
            "ibge_municipality_code",
            "age_group_code"        ,
            "sex_code"              ,
        ],

        key         =lambda column: column.map(_age_order) if column.name == "age_group_code" else column,
        kind        ="stable",
        ignore_index=True    ,
    )
    return (population,)


@app.cell
def _(config, query_url, read_sidra, require):
    _sexes = (config.sex_total, *config.sexes)

    _url      = query_url (      "1", _sexes, (config.age_total,))
    _national = read_sidra(_url, "1", _sexes, (config.age_total,))

    require(
        len(_national) == len(_sexes)                    and
            _national["D4C"].is_unique                   and
            _national["D1C"].eq("1").fillna(False).all(),

        "Duplicate, missing or unexpected national controls.",
    )

    national_totals = {
        code : int(value)
        for code, value in zip(_national["D4C"], _national["V"], strict=True)
    }
    return (national_totals,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## VALIDATE AND PUBLISHING
    """)
    return


@app.cell
def _(config, municipal_totals, national_totals, pd, population, require):
    _code = "ibge_municipality_code"
    _key  = [
        _code,

        "sex_code"      ,
        "age_group_code",
    ]

    _by_municipality = population      .groupby  (_code)
    _control         = municipal_totals.set_index(_code)

    _sums   = _by_municipality              ["resident_population"].sum().to_dict()
    _by_sex = population.groupby("sex_code")["resident_population"].sum().to_dict()

    _checks = {
        "Municipality codes contain seven digits"                    : population[_code].str.fullmatch(r"[0-9]{7}", na=False).all(),
        "Municipality-sex-age primary key is unique"                 : not population.duplicated(_key).any()                       ,
        "Municipality codes match the Census territorial control"    : set(population[_code]) == set(_control.index)               ,
        "Municipal age-sex sums match the official municipal totals" : _sums == _control["resident_population"].to_dict()          ,

        "Exactly 42 records per municipality" : _by_municipality.size().eq(len(config.sexes) * len(config.ages)).all(),

        "Municipal sums match the national total and both sex totals" : (
            _by_sex == {code: national_totals[code] for code in config.sexes}                 and
            int(population["resident_population"].sum()) == national_totals[config.sex_total]
        ),
    }

    validation_results = pd.DataFrame({"check": _checks.keys(), "passed": _checks.values()})

    require(all(_checks.values()), "Validation failed: " + "; ".join(name for name, ok in _checks.items() if not ok))

    validated_summary = {
        "municipalities"           : len(_control  ),
        "records"                  : len(population),
        "population_total"         : int(population["resident_population"].sum())           ,
        "official_national_by_sex" : {code : national_totals[code] for code in config.sexes},
    }
    return validated_summary, validation_results


@app.cell
def _(mo, validation_results):
    mo.vstack([
        mo.ui.table(validation_results, selection=None),
    ])
    return


@app.cell
def _(
    category_labels,
    classifications,
    config,
    descriptor_url,
    validated_summary,
):
    metadata = {
        "description"    : "Municipal resident population by sex and exclusive five-year age group, 2022 Brazilian Census.",
        "reference_year" : 2022,

        "source" : {
            "name"      : "IBGE SIDRA — Censo Demográfico 2022"             ,
            "table"     : config.table                                      ,
            "table_url" : f"https://sidra.ibge.gov.br/tabela/{config.table}",

            "variable" : {
                "code"  : config.variable      ,
                "label" : "População residente",
                "unit"  : "Pessoas"            ,
            },

            "territorial_level" : "N6"          ,
            "descriptor_url"    : descriptor_url,
        },

        "classifications": {
            "sex" : {
                "code"       : "2"                         ,
                "label"      : classifications["2"]["Nome"],
                "categories" : [
                    {
                        "code"  : code                      ,
                        "label" : category_labels["2"][code],
                    }
                    for code in config.sexes
                ],
            },

            "age" : {
                "code"       : "287"                         ,
                "label"      : classifications["287"]["Nome"],
                "categories" : [
                    {
                        "code"  : code                        ,
                        "label" : category_labels["287"][code],
                        "order" : order                       ,
                    }
                    for order, code in enumerate(config.ages, 1)
                ],
            },
        },

        "validation" : validated_summary,
    }
    return (metadata,)


@app.cell
def _(ExitStack, config, json, metadata, mo, population, staged_path):
    csv_path      = config.root / "data"     / "municipal_population_2022.csv"
    metadata_path = config.root / "metadata" / "municipal_population.json"

    with ExitStack() as _stack:
        _csv_temp  = _stack.enter_context(staged_path(csv_path     ))
        _json_temp = _stack.enter_context(staged_path(metadata_path))

        population.to_csv(
            _csv_temp,

            index         =False  ,
            encoding      ="utf-8",
            sep           =","    ,
            lineterminator="\n"   ,
        )

        _json_temp.write_text(
            json.dumps(
                metadata,

                ensure_ascii=False,
                indent      =2    ,
            ) + "\n",

            encoding="utf-8",
        )

        _csv_temp .replace(csv_path     )
        _json_temp.replace(metadata_path)

    mo.md(f"Published files:\n\n- `{csv_path}`\n- `{metadata_path}`")
    return


if __name__ == "__main__":
    app.run()
