// ============================================================
// Schema check (run after the import)
// ============================================================
CALL db.schema.visualization();


// ============================================================
// Q1. Structure of each programme: courses and ECTS per section
// ============================================================
MATCH (p:Program)-[r:INCLUDES_COURSE]->(c:Course)
RETURN p.program_id AS programme,
       r.section_name AS section,
       count(DISTINCT c) AS courses,
       sum(r.credit_points) AS ects
ORDER BY programme, section;


// ============================================================
// Q2. Courses shared by both programmes
// ============================================================
MATCH (:Program {program_id: 'DMB0'})-[:INCLUDES_COURSE]->(c:Course)<-[:INCLUDES_COURSE]-(:Program {program_id: 'HMD0'})
RETURN DISTINCT c.course_id AS course, c.title AS title, c.credit_points AS ects
ORDER BY course;


// ============================================================
// Q3. Which courses teach about knowledge / ontologies / semantics?
// ============================================================
MATCH (c:Course)-[:HAS_TOPIC]->(t:Topic)
WHERE toLower(t.title) CONTAINS 'knowledge'
   OR toLower(t.title) CONTAINS 'ontolog'
   OR toLower(t.title) CONTAINS 'semantic'
RETURN c.course_id AS course, c.title AS title, count(t) AS matching_topics
ORDER BY matching_topics DESC, course;


// ============================================================
// Q4. The five most topic-heavy courses (with workload in hours)
// ============================================================
MATCH (c:Course)-[:HAS_TOPIC]->(t:Topic)
RETURN c.course_id AS course,
       c.title AS title,
       c.credit_points AS ects,
       count(t) AS topics,
       sum(t.total_hours) AS total_hours
ORDER BY topics DESC, total_hours DESC
LIMIT 5;


// ============================================================
// Q5. Graph view: everything connected to "Knowledge Management Systems"
//     (use the Graph view of the result, not the Table view)
// ============================================================
MATCH path = (p:Program)-[:INCLUDES_COURSE]->(c:Course {course_id: 'DE0739'})-[:HAS_TOPIC|HAS_OUTCOME]->(x)
RETURN path;


// ============================================================
// Bonus data-quality check: courses without any topic
// ============================================================
MATCH (c:Course)
WHERE NOT (c)-[:HAS_TOPIC]->()
RETURN c.course_id AS course, c.title AS title
ORDER BY course;
