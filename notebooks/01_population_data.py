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

        municipality_count=5570  ,
        safe_value_limit  =45_000,
        timeout           =90    ,

        uf_by_prefix=dict(
            zip(
                "11 12 13 14 15 16 17 21 22 23 24 25 26 27 28 29 31 32 33 35 41 42 43 50 51 52 53".split(),
                "RO AC AM RR PA AP TO MA PI CE RN PB PE AL SE BA MG ES RJ SP PR SC RS MS MT GO DF".split(),

                strict=True,
            )
        ),
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
    ## CHECK THE TABLE DEFINITION
    """)
    return


@app.cell
def _(config, fetch_json, require):
    descriptor_url = f"{config.api}/DescritoresTabela/t/{config.table}"

    descriptor = fetch_json(descriptor_url)


    require(isinstance(descriptor, dict)                                     , "Malformed table descriptor." )
    require(str(descriptor.get("Id")) == config.table                        , "Unexpected table ID."        )
    require(config.year in {str(p["Codigo"]) for p in descriptor["Periodos"]}, "2022 is unavailable."        )
    require(descriptor["QuantidadeDimensoes"] == 6                           , "Unexpected table dimensions.")

    _variable = next(
        v
        for v in descriptor["Variaveis"]
        if  str(v["Id"]) == config.variable
    )

    require(_variable["UnidadeMedida"] == "Pessoas"                             , "Unexpected population unit.")
    require({1, 6}.issubset({n["Id"] for n in descriptor["NiveisTerritoriais"]}), "Missing N1 or N6."          )

    classifications = {
        str(c["Id"]) : c
        for c in descriptor["Classificacoes"]
    }

    require(set(classifications) == {"2", "287", "286"}, "Unexpected classifications.")

    category_labels = {
        code : {
            str(c["Id"]) : c["Nome"]
            for c in classification["Categorias"]
        }
        for code, classification in classifications.items()
    }
    _age_codes = tuple(
        str(c["Id"])
        for c in classifications["287"]["Categorias"]
        if  c["NivelIdentacao"] == 1
    )

    require(_age_codes == config.ages, "The 21 exclusive age groups or their order changed.")

    require({category_labels["2"].get("4"), category_labels["2"].get("5")} == {"Homens", "Mulheres"}, "Unexpected sex labels.")

    for _classification, _total in (
        ("2"  , config.sex_total        ),
        ("287", config.age_total        ),
        ("286", config.declaration_total),
    ):
        require(category_labels[_classification].get(_total) == "Total", "Missing official total category.")
    return category_labels, classifications, descriptor_url


@app.cell
def _(category_labels, config, fetch_json, pd, require):
    def query_url(level, sexes, ages):
        territory = "all" if level == "6" else "1"

        return (
            f"{config.api}/values/t/{config.table}/n{level}/{territory}"
            f"/v/{config.variable}/p/{config.year}/c2/{','.join(sexes)}"
            f"/c287/{','.join(ages)}/c286/{config.declaration_total}/h/y"
        )

    def read_sidra(url, level, sexes, ages):
        """Check every returned dimension, category label, unit and value"""

        payload = fetch_json(url)

        require(isinstance(payload, list) and len(payload) > 1, f"No SIDRA records: {url}")

        _territory = "Município" if level == "6" else "Brasil"

        for dimension, label in enumerate(
            (_territory, "Variável", "Ano", "Sexo", "Idade", "Forma de declaração da idade"), 1
        ):
            require(payload[0].get(f"D{dimension}C") == f"{label} (Código)", "Unexpected SIDRA dimension order.")

        frame    = pd.DataFrame(payload[1:], dtype="string")
        expected = {
            "NC"  : level     ,
            "NN"  : _territory,
            "MC"  : "45"      ,
            "MN"  : "Pessoas" ,
            "D2C" : config.variable         ,
            "D2N" : "População residente"   ,
            "D3C" : config.year             ,
            "D3N" : config.year             ,
            "D6C" : config.declaration_total,
            "D6N" : "Total"                 ,
        }

        required = set(expected) | {"D1C", "D1N", "D4C", "D4N", "D5C", "D5N", "V"}

        require(required.issubset(frame.columns)            , "Missing SIDRA columns."             )
        require(not frame[list(required)].isna().any().any(), "Missing SIDRA values or dimensions.")

        frame = frame.apply(lambda column: column.str.strip())
        for column, value in expected.items():
            require(frame[column].eq(value).all(), f"Unexpected {column}; expected {value}.")

        require(set(frame["D4C"]) == set(sexes), "Unexpected returned sex categories.")
        require(set(frame["D5C"]) == set(ages ), "Unexpected returned age categories.")

        for dimension, classification in ((4, "2"), (5, "287")):
            labels = frame[f"D{dimension}C"].map(category_labels[classification])

            require(frame[f"D{dimension}N"].eq(labels).all(), "Inconsistent official category labels.")

        values  = frame["V"] .replace  ("-", "0")
        invalid = ~values.str.fullmatch(r"[0-9]+", na=False)

        require(not invalid.any(), f"Invalid population values: {frame.loc[invalid, 'V'].unique().tolist()}")

        frame["V"] = pd.to_numeric(values, errors="raise").astype("int64")

        require(frame["V"].ge(0).all(), "Negative population.")

        return frame

    return query_url, read_sidra


@app.cell
def _(config, pd, require):
    def municipal_frame(raw):
        codes = raw["D1C"]

        require(codes.str.fullmatch(r"[0-9]{7}", na=False).all(), "Invalid seven-digit IBGE codes.")

        location = raw["D1N"].str.extract(r"^(.+?)\s+(?:-\s+|\()([A-Z]{2})\)?$")

        require(not location.isna().any().any(), "Cannot parse municipality names and UFs.")

        require(location[1].eq(codes.str[:2].map(config.uf_by_prefix)).fillna(False).all(), "IBGE code/UF mismatch.")

        return pd.DataFrame({
            "codigo_municipio_ibge" : codes     ,
            "codigo_faixa_etaria"   : raw["D5C"],
            "populacao_residente"   : raw["V"  ],
            "municipio"             : location[0].str.strip(),
            "uf"                    : location[1]            ,
            "codigo_sexo"           : raw["D4C"],
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
    municipal_total_url = query_url("6", (config.sex_total,), (config.age_total,))

    municipal_totals = municipal_frame(
        read_sidra(
            municipal_total_url, "6", (config.sex_total,), (config.age_total,)
        )
    )

    require(len(municipal_totals) == config.municipality_count , "Unexpected 2022 Census N6 coverage.")
    require(municipal_totals["codigo_municipio_ibge"].is_unique, "Duplicate Census territory codes."  )

    batch_size = config.safe_value_limit // (len(municipal_totals) * len(config.sexes))

    require(batch_size >= 1, "A single age group exceeds the SIDRA request limit.")

    age_batches = [config.ages[i:i + batch_size]      for i    in range(0, len(config.ages), batch_size)]
    batch_urls  = [query_url("6", config.sexes, ages) for ages in age_batches]
    return age_batches, batch_urls, municipal_total_url, municipal_totals


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
            "codigo_municipio_ibge",
            "codigo_faixa_etaria"  ,
            "codigo_sexo"          ,
        ],

        key         =lambda column: column.map(_age_order) if column.name == "codigo_faixa_etaria" else column,
        kind        ="stable",
        ignore_index=True    ,
    )
    return (population,)


@app.cell
def _(config, query_url, read_sidra, require):
    _sexes = (config.sex_total, *config.sexes)

    national_total_url = query_url (                    "1", _sexes, (config.age_total,))
    _national          = read_sidra(national_total_url, "1", _sexes, (config.age_total,))

    require(len(_national) == 3 and _national["D4C"].is_unique                    , "Duplicate or missing national controls.")
    require(_national["D1C"].eq("1").all() and _national["D1N"].eq("Brasil").all(), "Unexpected national territory."         )

    national_totals = {
        code : int(value)
        for code, value in zip(_national["D4C"], _national["V"], strict=True)
    }
    return national_total_url, national_totals


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## VALIDATE AND PUBLISHING
    """)
    return


@app.cell
def _(config, municipal_totals, national_totals, pd, population, require):
    _code = "codigo_municipio_ibge"
    _key  = [
        _code,

        "codigo_sexo"        ,
        "codigo_faixa_etaria",
    ]

    _by_municipality = population      .groupby  (_code)
    _control         = municipal_totals.set_index(_code)

    _sums = _by_municipality["populacao_residente"].sum().to_dict()

    _by_sex = population.groupby("codigo_sexo")["populacao_residente"].sum      (     ).to_dict()
    _labels = population[[_code, "municipio", "uf"]].drop_duplicates().set_index(_code)

    _checks = {
        "Table, period, levels, classifications, labels and units validated": True,
        "Population contains only nonnegative integers; '-' converted to zero": True,
        "Municipality-sex-age primary key is unique": not population.duplicated(_key).any(),
        "Census 2022 municipality codes match the same-table territorial control":
            set(population[_code]) == set(_control.index) and len(_control) == config.municipality_count,
        "All 27 UFs and valid seven-digit IBGE codes are present":
            set(population["uf"]) == set(config.uf_by_prefix.values()),
        "Municipality names and UFs match the territorial control":
            _labels.sort_index().equals(_control[["municipio", "uf"]].sort_index()),
        "Exactly 42 records, two sexes and 21 ages per municipality":
            _by_municipality.size().eq(42).all()
            and _by_municipality["codigo_sexo"].nunique().eq(2).all()
            and _by_municipality["codigo_faixa_etaria"].nunique().eq(21).all(),
        "Expected municipality × sex × age record count": len(population) == config.municipality_count * 42,
        "Every municipal age-sex sum matches its official total":
            _sums == _control["populacao_residente"].to_dict(),
        "Municipal sums match both official national sex totals":
            _by_sex == {code: national_totals[code] for code in config.sexes},
        "Municipal sum and national sex sums match the official Brazil total":
            int(population["populacao_residente"].sum()) == national_totals[config.sex_total]
            == sum(national_totals[code] for code in config.sexes),
    }
    validation_results = pd.DataFrame({"check": _checks.keys(), "passed": _checks.values()})
    require(all(_checks.values()), "Validation failed: " + "; ".join(name for name, ok in _checks.items() if not ok))
    validated_summary = {
        "municipalities": len(_control),
        "records": len(population),
        "population_total": int(population["populacao_residente"].sum()),
        "official_national_total": national_totals[config.sex_total],
        "official_national_by_sex": {code: national_totals[code] for code in config.sexes},
    }
    return validated_summary, validation_results


@app.cell
def _(mo, population, validated_summary, validation_results):
    mo.vstack([
        mo.md(f"**All checks passed.** {validated_summary['municipalities']:,} N6 units; "
              f"{validated_summary['records']:,} records; "
              f"{validated_summary['population_total']:,} residents."),
        mo.ui.table(validation_results, selection=None),
        mo.md("### Data preview"),
        mo.ui.table(population.head(12), selection=None),
    ])
    return


@app.cell
def _(
    batch_urls,
    category_labels,
    classifications,
    config,
    descriptor_url,
    municipal_total_url,
    national_total_url,
    population,
    validated_summary,
):
    _descriptions = (
        ("Official seven-digit IBGE municipality code.", "string", None),
        ("Official municipality name, without its UF suffix.", "string", None),
        ("Two-letter Brazilian federation-unit abbreviation.", "string", None),
        ("Official SIDRA sex category code; labels are documented below.", "string", None),
        ("Official SIDRA age-group code; labels and chronological order are documented below.", "string", None),
        ("2022 Census resident population for the municipality, sex and age group.", "integer", "persons"),
    )
    metadata = {
        "description": "Municipal resident population by sex and exclusive five-year age group, 2022 Brazilian Census (universe results).",
        "reference_year": 2022,
        "source": {
            "name": "IBGE SIDRA — Censo Demográfico 2022",
            "table": config.table,
            "table_url": f"https://sidra.ibge.gov.br/tabela/{config.table}",
            "variable": {"code": config.variable, "label": "População residente", "unit": "Pessoas"},
            "territorial_level": "N6",
            "descriptor_url": descriptor_url,
            "query_urls": {
                "municipal_age_batches": batch_urls,
                "municipal_total_control": municipal_total_url,
                "national_total_and_sex_controls": national_total_url,
            },
        },
        "territorial_coverage": "5,570 Census 2022 N6 units, including Brasília (DF) and Fernando de Noronha (PE); verified against table 9514 municipal totals for 2022.",
        "columns": [
            {"name": name, "description": description, "logical_type": dtype, "unit": unit}
            for name, (description, dtype, unit) in zip(population.columns, _descriptions, strict=True)
        ],
        "primary_key": ["codigo_municipio_ibge", "codigo_sexo", "codigo_faixa_etaria"],
        "classifications": {
            "sex": {
                "code": "2", "label": classifications["2"]["Nome"],
                "categories": [{"code": code, "label": category_labels["2"][code]} for code in config.sexes],
            },
            "age": {
                "code": "287", "label": classifications["287"]["Nome"],
                "categories": [
                    {"code": code, "label": category_labels["287"][code], "order": order}
                    for order, code in enumerate(config.ages, 1)
                ],
            },
            "age_declaration": {
                "code": "286", "label": classifications["286"]["Nome"],
                "selected_category": {"code": config.declaration_total, "label": "Total"},
            },
        },
        "control_categories": {"sex_total": config.sex_total, "age_total": config.age_total},
        "population_rules": {"minimum": 0, "sidra_absolute_zero_symbol": "-", "other_symbols": "rejected"},
        "sort_order": ["codigo_municipio_ibge", "chronological age-group order", "codigo_sexo"],
        "csv": {"encoding": "UTF-8", "delimiter": ",", "index": False, "read_codes_as": "string"},
        "validation": validated_summary,
    }
    return (metadata,)


@app.cell
def _(ExitStack, config, json, metadata, mo, population, staged_path):
    csv_path = config.root / "data" / "municipal_population_2022.csv"
    metadata_path = config.root / "metadata" / "municipal_population.json"
    # Prepare both complete files before replacing either published product.
    with ExitStack() as _stack:
        _csv_temp = _stack.enter_context(staged_path(csv_path))
        _json_temp = _stack.enter_context(staged_path(metadata_path))
        population.to_csv(_csv_temp, index=False, encoding="utf-8", sep=",", lineterminator="\n")
        _json_temp.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _csv_temp.replace(csv_path)
        _json_temp.replace(metadata_path)
    mo.md(f"## 4. Published files\n\n- CSV: `{csv_path}`\n- Data dictionary: `{metadata_path}`")
    return


if __name__ == "__main__":
    app.run()
