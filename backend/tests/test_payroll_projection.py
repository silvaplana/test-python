from datetime import date

from seasons.projection import payroll_projection

END = date(2027, 6, 30)


def op(day, category, amount):
    return {"date": day, "category": category, "amount": amount}


# Operations reelles du club (montants de 2026), le 9 octobre 2026.
ROWS = (
    [op(f"2026-{m:02d}-28", "Salaires", -579.46) for m in (2, 3, 4, 5, 6, 8, 9, 10)]
    + [op("2026-03-15", "URSSAF", -218.0), op("2026-05-15", "URSSAF", -436.0), op("2026-07-15", "URSSAF", -436.0),
       op("2026-08-15", "URSSAF", -218.0), op("2026-09-15", "URSSAF", -218.0)]
    + [op(f"2026-{m:02d}-05", "Mutuelle", -58.15) for m in range(2, 10)]
    + [op("2026-09-20", "Matériel", -120.0), op("2026-10-08", "Cotisations en ligne", 6746.2)]
)


def test_projection_until_the_end_of_the_season():
    result = payroll_projection(ROWS, END, date(2026, 10, 9))
    lines = {line["category"]: line for line in result["lines"]}
    assert list(lines) == ["Salaires", "URSSAF", "Mutuelle"]

    # Salaire regulier, deja paye en octobre : novembre a juin.
    salary = lines["Salaires"]
    assert (salary["basis"], salary["monthly"], salary["paidThisMonth"]) == ("regular", 579.46, True)
    assert (salary["firstMonth"], salary["lastMonth"], salary["months"], salary["amount"]) == ("2026-11", "2027-06", 8, 4635.68)
    assert [m["month"] for m in salary["basisMonths"]] == ["2026-08", "2026-09", "2026-10"]

    # URSSAF irreguliere (mois sautes puis doubles) : moyenne d'avril a septembre.
    urssaf = lines["URSSAF"]
    assert (urssaf["basis"], urssaf["monthly"], urssaf["paidThisMonth"]) == ("average", 218.0, False)
    assert [(m["month"], m["amount"]) for m in urssaf["basisMonths"]] == [
        ("2026-04", 0.0), ("2026-05", 436.0), ("2026-06", 0.0), ("2026-07", 436.0), ("2026-08", 218.0), ("2026-09", 218.0),
    ]
    assert (urssaf["firstMonth"], urssaf["months"], urssaf["amount"]) == ("2026-10", 9, 1962.0)

    # Mutuelle reguliere, pas encore payee en octobre.
    assert (lines["Mutuelle"]["monthly"], lines["Mutuelle"]["months"], lines["Mutuelle"]["amount"]) == (58.15, 9, 523.35)
    assert result["total"] == 7121.03
    assert result["seasonEnd"] == "2027-06-30"


def test_last_month_of_the_season_and_missing_category():
    # Fin juin, salaire de juin paye : plus rien a payer cette saison.
    rows = [op(f"2027-{m:02d}-28", "Salaires", -600.0) for m in (4, 5, 6)]
    result = payroll_projection(rows, END, date(2027, 6, 29))
    assert [line["category"] for line in result["lines"]] == ["Salaires"]  # pas d'URSSAF ni de mutuelle connues
    assert (result["lines"][0]["months"], result["lines"][0]["firstMonth"], result["total"]) == (0, None, 0.0)
    # Meme jour, salaire de juin pas encore paye : un mois.
    result = payroll_projection(rows[:2], END, date(2027, 6, 29))
    # 2 mois d'historique seulement : moyenne sur ces 2 mois, pas sur 6.
    line = result["lines"][0]
    assert (line["months"], line["basis"], line["monthly"], line["amount"]) == (1, "average", 600.0, 600.0)
    assert [m["month"] for m in line["basisMonths"]] == ["2027-04", "2027-05"]
