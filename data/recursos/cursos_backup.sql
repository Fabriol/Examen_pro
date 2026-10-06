
-- =====================================================
-- BASE DE DATOS PARA EXAMEN PRACTICO
-- Sistema: Gestión de Cursos en Línea
-- Base de datos sugerida: cursosdb
-- =====================================================

DROP TABLE IF EXISTS matriculas;
DROP TABLE IF EXISTS cursos;
DROP TABLE IF EXISTS instructores;
DROP TABLE IF EXISTS estudiantes;

CREATE TABLE estudiantes (
    id_estudiante SERIAL PRIMARY KEY,
    nombre VARCHAR(50),
    apellido VARCHAR(50),
    correo VARCHAR(100)
);

CREATE TABLE instructores (
    id_instructor SERIAL PRIMARY KEY,
    nombre VARCHAR(60),
    especialidad VARCHAR(100)
);

CREATE TABLE cursos (
    id_curso SERIAL PRIMARY KEY,
    nombre VARCHAR(100),
    nivel VARCHAR(20),
    cupos_disponibles INT,
    id_instructor INT,
    FOREIGN KEY (id_instructor) REFERENCES instructores(id_instructor)
);

CREATE TABLE matriculas (
    id_matricula SERIAL PRIMARY KEY,
    id_estudiante INT,
    id_curso INT,
    fecha_matricula DATE,
    FOREIGN KEY (id_estudiante) REFERENCES estudiantes(id_estudiante),
    FOREIGN KEY (id_curso) REFERENCES cursos(id_curso)
);

INSERT INTO estudiantes (nombre, apellido, correo) VALUES
('Ana','Lopez','ana.lopez@email.com'),
('Carlos','Perez','carlos.perez@email.com'),
('Maria','Gomez','maria.gomez@email.com'),
('Luis','Torres','luis.torres@email.com'),
('Sofia','Ramirez','sofia.ramirez@email.com'),
('Pedro','Vega','pedro.vega@email.com'),
('Diana','Mendoza','diana.mendoza@email.com');

INSERT INTO instructores (nombre, especialidad) VALUES
('Juan Martinez','Programación'),
('Laura Sanchez','Bases de Datos'),
('Pedro Castillo','Desarrollo Web'),
('Andrea Rojas','Ingeniería de Software');

INSERT INTO cursos (nombre, nivel, cupos_disponibles, id_instructor) VALUES
('Introducción a la Programación','Basico',40,1),
('Bases de Datos con SQL','Intermedio',35,2),
('Desarrollo Web con Angular','Avanzado',30,3),
('Modelado de Bases de Datos','Intermedio',25,2),
('Arquitectura de Software','Avanzado',20,4);

INSERT INTO matriculas (id_estudiante, id_curso, fecha_matricula) VALUES
(1,1,'2025-01-10'),
(2,1,'2025-01-11'),
(3,2,'2025-01-12'),
(4,3,'2025-01-15'),
(5,2,'2025-01-20'),
(1,4,'2025-01-22'),
(6,3,'2025-01-25'),
(7,5,'2025-01-28');
