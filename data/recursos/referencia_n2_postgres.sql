-- ============================================================
-- REFERENCIA CASO N2 (EduTech Academy) - PostgreSQL
-- Ejecutar DESPUES de restaurar cursos_backup.sql
-- ============================================================

-- 2a. Correo unico
ALTER TABLE estudiantes ADD CONSTRAINT uq_estudiantes_correo UNIQUE (correo);

-- 2b. Nivel restringido. El backup trae 'Basico' (sin tilde): normalizar ANTES de crear el CHECK
UPDATE cursos SET nivel = 'Básico' WHERE nivel = 'Basico';
ALTER TABLE cursos ADD CONSTRAINT ck_cursos_nivel CHECK (nivel IN ('Básico','Intermedio','Avanzado'));

-- 3. Cupos entre 10 y 60
ALTER TABLE cursos ADD CONSTRAINT ck_cursos_cupos CHECK (cupos_disponibles BETWEEN 10 AND 60);

-- 4a. Vista: estudiante, curso, fecha de matricula, nivel
CREATE VIEW vista_matriculas AS
SELECT e.nombre || ' ' || e.apellido AS estudiante,
       c.nombre AS curso,
       m.fecha_matricula,
       c.nivel
FROM matriculas m
JOIN estudiantes e ON e.id_estudiante = m.id_estudiante
JOIN cursos c      ON c.id_curso      = m.id_curso;

-- 4b. Vista: curso, instructor, especialidad
CREATE VIEW vista_cursos_instructores AS
SELECT c.nombre AS curso,
       i.nombre AS instructor,
       i.especialidad
FROM cursos c
JOIN instructores i ON i.id_instructor = c.id_instructor;

-- 5. Usuarios y privilegios
CREATE ROLE administrador LOGIN PASSWORD 'Admin#2026';
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO administrador;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO administrador;

CREATE ROLE usuario_consultas LOGIN PASSWORD 'Consulta#2026';
GRANT SELECT ON vista_matriculas, vista_cursos_instructores TO usuario_consultas;

-- 6a. Trigger: al eliminar un curso, eliminar sus matriculas (BEFORE, por la FK)
CREATE OR REPLACE FUNCTION fn_eliminar_matriculas_curso() RETURNS trigger AS $$
BEGIN
    DELETE FROM matriculas WHERE id_curso = OLD.id_curso;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_eliminar_matriculas_curso
BEFORE DELETE ON cursos
FOR EACH ROW EXECUTE FUNCTION fn_eliminar_matriculas_curso();

-- 6b. Trigger: al insertar una matricula, cupos - 1
CREATE OR REPLACE FUNCTION fn_reducir_cupos() RETURNS trigger AS $$
BEGIN
    UPDATE cursos SET cupos_disponibles = cupos_disponibles - 1
    WHERE id_curso = NEW.id_curso;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_reducir_cupos
AFTER INSERT ON matriculas
FOR EACH ROW EXECUTE FUNCTION fn_reducir_cupos();
