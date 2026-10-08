"""
Load the KMS_Dataset CSV files into a Neo4j AuraDB instance.

Usage:
    pip install neo4j pandas
    export NEO4J_URI="neo4j+s://xxxxxxxx.databases.neo4j.io"
    export NEO4J_USER="neo4j"
    export NEO4J_PASSWORD="your-password"
    export NEO4J_DATABASE="xxxxxxxx"        # optional: the database name from the credentials file
    python import_to_auradb.py --data ./KMS_Dataset --reset

On Windows (PowerShell) use:  $env:NEO4J_URI="..."  instead of export.
"""
import argparse
import json
import os
from pathlib import Path

import pandas as pd
from neo4j import GraphDatabase


def read(path):
    """Read a CSV (removing the BOM) and return a list of plain dicts.
    Missing values (NaN) become None, so Neo4j simply skips those properties."""
    df = pd.read_csv(path, encoding="utf-8-sig")
    return json.loads(df.to_json(orient="records"))


def drop(rows, *keys):
    return [{k: v for k, v in r.items() if k not in keys} for r in rows]


CONSTRAINTS = [
    "CREATE CONSTRAINT program_id IF NOT EXISTS FOR (n:Program) REQUIRE n.program_id IS UNIQUE",
    "CREATE CONSTRAINT field_id IF NOT EXISTS FOR (n:StudyField) REQUIRE n.study_field_id IS UNIQUE",
    "CREATE CONSTRAINT course_id IF NOT EXISTS FOR (n:Course) REQUIRE n.course_id IS UNIQUE",
    "CREATE CONSTRAINT topic_id IF NOT EXISTS FOR (n:Topic) REQUIRE n.topic_id IS UNIQUE",
    "CREATE CONSTRAINT outcome_id IF NOT EXISTS FOR (n:LearningOutcome) REQUIRE n.outcome_id IS UNIQUE",
]


def run(session, query, rows):
    session.run(query, rows=rows).consume()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="./KMS_Dataset", help="path to the cloned KMS_Dataset folder")
    ap.add_argument("--reset", action="store_true", help="delete all existing nodes first")
    args = ap.parse_args()
    d = Path(args.data)

    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
    )
    driver.verify_connectivity()
    print("Connected to", os.environ["NEO4J_URI"])

    programs = read(d / "nodes/nodes_study_programs.csv")
    fields = read(d / "nodes/nodes_study_fields.csv")
    courses = read(d / "nodes/nodes_study_courses.csv")
    topics = read(d / "nodes/nodes_course_topics.csv")
    outcomes = read(d / "nodes/nodes_learning_outcomes.csv")

    program_field = read(d / "edges/program+study_field.csv")
    program_course = read(d / "edges/program+course.csv")
    course_topic = read(d / "edges/course+topic.csv")
    course_outcome = read(d / "edges/course+learning_outcome.csv")

    # AuraDB instances may use the instance ID as the database name (see NEO4J_DATABASE in the credentials file)
    with driver.session(database=os.environ.get("NEO4J_DATABASE") or None) as s:
        if args.reset:
            s.run("MATCH (n) DETACH DELETE n").consume()
            print("Existing data deleted")

        for c in CONSTRAINTS:
            s.run(c).consume()
        print("Constraints created")

        # ---------- nodes ----------
        run(s, "UNWIND $rows AS row MERGE (n:Program {program_id: row.program_id}) SET n += row", programs)
        run(s, "UNWIND $rows AS row MERGE (n:StudyField {study_field_id: row.study_field_id}) SET n += row", fields)
        run(s, "UNWIND $rows AS row MERGE (n:Course {course_id: row.course_id}) SET n += row", courses)

        # Topic: course_id is kept out of the node (it becomes the HAS_TOPIC relationship)
        # and total_hours is added to make queries easier.
        topic_rows = drop(topics, "course_id")
        run(
            s,
            """
            UNWIND $rows AS row
            MERGE (n:Topic {topic_id: row.topic_id})
            SET n += row,
                n.total_hours = coalesce(row.intramural_contact_hours, 0)
                              + coalesce(row.intramural_independent_hours, 0)
                              + coalesce(row.extramural_contact_hours, 0)
                              + coalesce(row.extramural_independent_hours, 0)
            """,
            topic_rows,
        )

        # LearningOutcome: one common label plus a specific one (ProgrammeOutcome / CourseOutcome)
        outcome_rows = drop(outcomes, "owner_id")
        run(s, "UNWIND $rows AS row MERGE (n:LearningOutcome {outcome_id: row.outcome_id}) SET n += row", outcome_rows)
        s.run("MATCH (n:LearningOutcome {scope:'programme'}) SET n:ProgrammeOutcome").consume()
        s.run("MATCH (n:LearningOutcome {scope:'course'}) SET n:CourseOutcome").consume()
        print("Nodes created")

        # ---------- relationships ----------
        run(
            s,
            """
            UNWIND $rows AS row
            MATCH (p:Program {program_id: row.program_id})
            MATCH (f:StudyField {study_field_id: row.study_field_id})
            MERGE (p)-[:IN_FIELD]->(f)
            """,
            program_field,
        )

        # A course can appear in the same programme more than once (different section),
        # so CREATE is used here instead of MERGE. Run with --reset to avoid duplicates.
        run(
            s,
            """
            UNWIND $rows AS row
            MATCH (p:Program {program_id: row.program_id})
            MATCH (c:Course {course_id: row.course_id})
            CREATE (p)-[:INCLUDES_COURSE {
                credit_points: row.credit_points,
                section_code: row.section_code,
                section_name: row.section_name,
                subsection_name: row.subsection_name
            }]->(c)
            """,
            program_course,
        )

        run(
            s,
            """
            UNWIND $rows AS row
            MATCH (c:Course {course_id: row.course_id})
            MATCH (t:Topic {topic_id: row.topic_id})
            MERGE (c)-[:HAS_TOPIC]->(t)
            """,
            course_topic,
        )

        run(
            s,
            """
            UNWIND $rows AS row
            MATCH (c:Course {course_id: row.course_id})
            MATCH (o:LearningOutcome {outcome_id: row.outcome_id})
            MERGE (c)-[:HAS_OUTCOME]->(o)
            """,
            course_outcome,
        )

        # programme-level outcomes are owned by a programme (owner_id)
        programme_outcomes = [
            {"program_id": o["owner_id"], "outcome_id": o["outcome_id"]}
            for o in outcomes
            if o["scope"] == "programme"
        ]
        run(
            s,
            """
            UNWIND $rows AS row
            MATCH (p:Program {program_id: row.program_id})
            MATCH (o:LearningOutcome {outcome_id: row.outcome_id})
            MERGE (p)-[:HAS_OUTCOME]->(o)
            """,
            programme_outcomes,
        )
        print("Relationships created")

        # ---------- check ----------
        print("\nNode counts:")
        for r in s.run("MATCH (n) RETURN labels(n) AS labels, count(*) AS n ORDER BY n DESC"):
            print("  ", r["labels"], r["n"])
        print("Relationship counts:")
        for r in s.run("MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS n ORDER BY n DESC"):
            print("  ", r["type"], r["n"])

    driver.close()


if __name__ == "__main__":
    main()
