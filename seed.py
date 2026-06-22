#!/usr/bin/env python3
"""
seed.py — Wipe the database and populate it with 10 detailed applicant markets.

Run from the project root:
    ANTHROPIC_API_KEY=sk-... python3 seed.py

Without ANTHROPIC_API_KEY the markets are still created but llm_score and
llm_summary will be NULL (the opening price is then purely ML-derived).
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from market.core.llm_assessor import assess_extracurriculars, blend_probability
from market.core.lmsr import entropy_scaled_b, seed_state
from market.db.models import Base, Market, User
from market.db.session import AsyncSessionLocal, create_tables, engine

# ── House admin ───────────────────────────────────────────────────────────────

HOUSE = dict(
    username = "house",
    email    = "house@admissionsmarket.com",
    is_admin = True,
    balance  = 100_000.0,
)

# ── 10 detailed applicant profiles ───────────────────────────────────────────

PROFILES: list[dict] = [
    {
        "school":      "Harvard University",
        "round":       "EA",
        "gpa_uw":      4.0,
        "gpa_w":       4.9,
        "sat":         1590,
        "gender":      "Male",
        "income_ord":  3,
        "flair_field": "STEM",
        "extracurriculars": (
            "4-time AIME qualifier (top 5% nationally); scored 138/150 on AMC 12. "
            "MIT PRIMES research participant — co-authored paper on combinatorial graph theory submitted to arXiv. "
            "USA Physics Olympiad semifinalist (top 400 in the country). "
            "Founded and leads high school's competitive math team (30 members), won state championship two years running. "
            "Assistant instructor at local community college coding bootcamp, teaching Python to adult learners on weekends."
        ),
    },
    {
        "school":      "Massachusetts Institute of Technology",
        "round":       "RD",
        "gpa_uw":      3.95,
        "gpa_w":       4.7,
        "sat":         1560,
        "gender":      "Female",
        "income_ord":  1,
        "flair_field": "STEM",
        "extracurriculars": (
            "Captain of FIRST Robotics team; led team to World Championship semifinals in Houston. "
            "Intel Science & Engineering Fair regional winner; project on reinforcement learning for autonomous navigation. "
            "Co-authored ML paper accepted to NeurIPS workshop with university mentor. "
            "Runs free coding workshops for underserved middle schoolers in her district — 120 students taught over two years. "
            "Competitive swimmer, varsity letter three years, district champion in 200m freestyle."
        ),
    },
    {
        "school":      "Stanford University",
        "round":       "EA",
        "gpa_uw":      4.0,
        "gpa_w":       5.0,
        "sat":         1580,
        "gender":      "Male",
        "income_ord":  4,
        "flair_field": "STEM",
        "extracurriculars": (
            "Founded EdTech startup at 16 — AI-powered tutoring platform with 8,000 monthly active users and $60k ARR. "
            "Google CSSI summer intern; shipped a production feature used by 2M+ users. "
            "Won three major hackathons including HackMIT and TreeHacks; projects open-sourced with 4,000+ GitHub stars. "
            "Published op-ed in TechCrunch on AI ethics in education. "
            "Varsity tennis captain, ranked top 50 in USTA 18-and-under juniors nationally."
        ),
    },
    {
        "school":      "Yale University",
        "round":       "EA",
        "gpa_uw":      3.95,
        "gpa_w":       4.6,
        "sat":         1530,
        "gender":      "Female",
        "income_ord":  2,
        "flair_field": "Art_Hum",
        "extracurriculars": (
            "National champion, Lincoln-Douglas debate (Tournament of Champions and NSDA nationals). "
            "Published debut short story collection through a regional indie press — reviewed in School Library Journal. "
            "First chair violinist, All-State Orchestra three consecutive years; performed at Carnegie Hall with youth ensemble. "
            "Editor-in-chief of school literary magazine, grew readership from 200 to 2,000+ monthly readers. "
            "Founded after-school creative writing program for Title I elementary students; secured $15k grant to sustain it."
        ),
    },
    {
        "school":      "Princeton University",
        "round":       "ED",
        "gpa_uw":      3.9,
        "gpa_w":       4.5,
        "sat":         1550,
        "gender":      "Male",
        "income_ord":  3,
        "flair_field": "SocSci",
        "extracurriculars": (
            "Summer research intern at Brookings Institution; co-wrote policy brief on housing affordability presented to Congressional staffers. "
            "Secretary-General of Harvard Model UN — organised conference for 1,200 delegates across 40 schools. "
            "Interned with state senator's office for two legislative sessions; drafted constituent communications and attended committee hearings. "
            "Founded school's first economics club; organised speaker series featuring Fed economists and local CEOs. "
            "Published two research notes on labour market trends in a blind peer-reviewed high school economics journal."
        ),
    },
    {
        "school":      "Columbia University",
        "round":       "RD",
        "gpa_uw":      3.85,
        "gpa_w":       4.4,
        "sat":         1510,
        "gender":      "Female",
        "income_ord":  1,
        "flair_field": "STEM",
        "extracurriculars": (
            "Two-year research assistant in a Johns Hopkins oncology lab — contributed to dataset curation for a published Nature Medicine study. "
            "President of pre-med honor society (120 members); organised annual health fair serving 500+ community members. "
            "Clinical volunteer at county hospital, 350 hours across cardiology and paediatric wards. "
            "EMT certified; volunteers with local fire department EMS on weekends. "
            "Fluent in Mandarin and Spanish; tutors ESL patients in her immigrant community on language access in healthcare."
        ),
    },
    {
        "school":      "University of Chicago",
        "round":       "EA",
        "gpa_uw":      4.0,
        "gpa_w":       4.8,
        "sat":         1570,
        "act":         35,
        "gender":      "Female",
        "income_ord":  2,
        "flair_field": "STEM",
        "extracurriculars": (
            "Putnam Mathematical Competition — ranked in the top 200 nationally. "
            "Research Science Institute (RSI) participant — summer research at MIT on elliptic curve cryptography. "
            "USA Mathematical Olympiad qualifier two years running; Bronze medal, Pan American Girls Mathematical Olympiad. "
            "Founder of regional girls-in-math network, connecting 300+ students across 15 schools for mentorship. "
            "Plays piano at concert level; performed Rachmaninoff Piano Concerto No. 2 with regional youth symphony."
        ),
    },
    {
        "school":      "Northwestern University",
        "round":       "ED",
        "gpa_uw":      3.8,
        "gpa_w":       4.3,
        "sat":         1480,
        "gender":      "Female",
        "income_ord":  4,
        "flair_field": "Art_Hum",
        "extracurriculars": (
            "Editor-in-chief of award-winning student newspaper (won SPJ national student journalism award). "
            "Investigative feature on local school district budget inequities led to coverage by Chicago Tribune and prompted a board audit. "
            "Summer intern at NBC5 Chicago — produced three on-air segments that aired on the evening news. "
            "Founded a journalism mentorship non-profit connecting high school students with professional journalists — 45 mentors enrolled. "
            "Competitive swimmer, varsity four years; team co-captain senior year."
        ),
    },
    {
        "school":      "Duke University",
        "round":       "EA",
        "gpa_uw":      3.85,
        "gpa_w":       4.45,
        "sat":         1500,
        "gender":      "Male",
        "income_ord":  2,
        "flair_field": "STEM",
        "extracurriculars": (
            "Research assistant in a Duke lab studying pancreatic cancer biomarkers — contributed to data analysis for an ongoing clinical trial. "
            "Founded school's first pre-med club; organised annual healthcare career symposium with 12 physician speakers. "
            "Hospital volunteer, 320 hours in oncology and emergency medicine; certified Patient Care Volunteer. "
            "EMT-Basic certified; active with county volunteer EMS squad, averaging 10 shifts per month. "
            "Eagle Scout; led community project building a sensory garden at a children's hospital — raised $8,000 in donations."
        ),
    },
    {
        "school":      "University of California, Los Angeles",
        "round":       "RD",
        "gpa_uw":      3.9,
        "gpa_w":       4.5,
        "sat":         1520,
        "gender":      "Male",
        "income_ord":  1,
        "flair_field": "STEM",
        "extracurriculars": (
            "Founded school's IEEE Student Branch — grew to 60 members and partnered with a local engineering firm for project sponsorships. "
            "Won three collegiate-level hackathons (LA Hacks, CalHacks, SoCal Tech); projects include an open-source IoT energy monitor with 11k GitHub stars. "
            "Early-start undergraduate researcher at Cal State LA — working on antenna design for 5G applications, paper under review at IEEE Transactions. "
            "Built and sold 15 custom mechanical keyboards, self-funding further research components. "
            "First-generation college student; tutors 12 peers in physics and calculus through a self-organised weekly study group."
        ),
    },
]

# ── ML prediction helper ──────────────────────────────────────────────────────

# Pre-computed probabilities from local model run (avoids needing ML deps in prod).
_PRECOMPUTED: dict[str, float] = {
    "Harvard University":                    0.653,
    "Massachusetts Institute of Technology": 0.098,
    "Stanford University":                   0.091,
    "Yale University":                       0.500,
    "Princeton University":                  0.671,
    "Columbia University":                   0.563,
    "University of Chicago":                 0.113,
    "Northwestern University":               0.147,
    "Duke University":                       0.114,
    "University of California, Los Angeles": 0.243,
}

def ml_predict(p: dict) -> float | None:
    school = p["school"]
    if school in _PRECOMPUTED:
        return _PRECOMPUTED[school]
    try:
        from model.predict import load_model, predict_admission
        arts = load_model()
        prob = predict_admission(
            arts,
            school      = school,
            gpa_uw      = p.get("gpa_uw"),
            gpa_w       = p.get("gpa_w"),
            sat         = p.get("sat"),
            act         = p.get("act"),
            round_      = p.get("round", "RD"),
            gender      = p.get("gender"),
            race        = p.get("race"),
            income_ord  = p.get("income_ord"),
            flair_field = p.get("flair_field"),
        )
        return float(max(0.01, min(0.99, prob)))
    except Exception as exc:
        print(f"    ML predict failed ({exc}), using 0.50 fallback")
        return None


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    # Drop all tables then recreate — works for both SQLite and Postgres.
    # This replaces the old SQLite-only file-delete approach.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    db_path = "market.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    await create_tables()
    print("Tables ready\n")

    has_llm = bool(os.getenv("ANTHROPIC_API_KEY"))
    if not has_llm:
        print("ANTHROPIC_API_KEY not set — markets will open at pure ML probability.\n")

    async with AsyncSessionLocal() as db:
        house = User(**HOUSE)
        db.add(house)
        await db.flush()
        print(f"House admin created  (id={house.id})\n")

        for i, p in enumerate(PROFILES, 1):
            label = f"[{i:02d}/10] {p['school']} · {p['round']}"
            print(label)

            ml_prob   = ml_predict(p)
            base_prob = ml_prob if ml_prob is not None else 0.50
            print(f"    ML prob   : {base_prob:.3f}")

            llm_score, llm_summary = await assess_extracurriculars(
                school           = p["school"],
                round_           = p["round"],
                extracurriculars = p["extracurriculars"],
            )
            if llm_score is not None:
                print(f"    LLM score : {llm_score:.1f}/10")
                print(f"    LLM note  : {(llm_summary or '')[:80]}...")
                opening = blend_probability(base_prob, llm_score)
            else:
                opening = base_prob
            print(f"    Opening   : {opening:.3f}  ({opening*100:.1f}% YES)\n")

            b = entropy_scaled_b(opening, b_max=100.0)
            q_yes, q_no = seed_state(opening, b)
            print(f"    b         : {b:.1f}  (max loss ${b * 0.6931:.2f})")

            market = Market(
                creator_id       = house.id,
                school           = p["school"],
                round            = p["round"],
                gpa_uw           = p.get("gpa_uw"),
                gpa_w            = p.get("gpa_w"),
                sat              = p.get("sat"),
                act              = p.get("act"),
                gender           = p.get("gender"),
                race             = p.get("race"),
                income_ord       = p.get("income_ord"),
                flair_field      = p.get("flair_field"),
                extracurriculars = p["extracurriculars"],
                llm_score        = llm_score,
                llm_summary      = llm_summary,
                b                = b,
                q_yes            = q_yes,
                q_no             = q_no,
                ml_prob          = ml_prob,
                status           = "open",
            )
            db.add(market)

        await db.commit()

    print("Done — 10 markets seeded.")


if __name__ == "__main__":
    asyncio.run(main())
