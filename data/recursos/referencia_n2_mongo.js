// REFERENCIA CASO N2 - MongoDB (mongosh)
// Los ids numericos coinciden con los de SQL (id_estudiante / id_curso) para poder cruzar datos.
use edutech

db.estudiantes.insertMany([
  { id_estudiante: 1, nombre: "Ana",    apellido: "Lopez",   correo: "ana.lopez@email.com" },
  { id_estudiante: 2, nombre: "Carlos", apellido: "Perez",   correo: "carlos.perez@email.com" },
  { id_estudiante: 3, nombre: "Maria",  apellido: "Gomez",   correo: "maria.gomez@email.com" }
])

db.cursos.insertMany([
  { id_curso: 1, nombre: "Introducción a la Programación", descripcion: "Fundamentos de programación",
    valoraciones: [
      { estudiante_id: 1, comentario: "Excelente inicio", puntuacion: 5, fecha: new Date("2025-02-01") },
      { estudiante_id: 2, comentario: "Muy útil",         puntuacion: 4, fecha: new Date("2025-02-02") } ] },
  { id_curso: 2, nombre: "Bases de Datos con SQL", descripcion: "SQL desde cero",
    valoraciones: [
      { estudiante_id: 3, comentario: "Muy claro",        puntuacion: 5, fecha: new Date("2025-02-03") } ] },
  { id_curso: 4, nombre: "Modelado de Bases de Datos", descripcion: "Modelo entidad-relación",
    valoraciones: [
      { estudiante_id: 1, comentario: "Buenos ejemplos",  puntuacion: 4, fecha: new Date("2025-02-04") } ] }
])

// 9a. Todas las valoraciones de un curso
db.cursos.find({ nombre: "Bases de Datos con SQL" }, { _id: 0, nombre: 1, valoraciones: 1 })

// 9b. Todos los comentarios de un estudiante
db.cursos.aggregate([
  { $unwind: "$valoraciones" },
  { $match: { "valoraciones.estudiante_id": 1 } },
  { $project: { _id: 0, curso: "$nombre", comentario: "$valoraciones.comentario",
                puntuacion: "$valoraciones.puntuacion", fecha: "$valoraciones.fecha" } }
])

// 9c. Comentarios de un estudiante en los cursos en que esta matriculado.
// Las matriculas estan en SQL: SELECT id_curso FROM matriculas WHERE id_estudiante = 1;  -> [1, 4]
db.cursos.aggregate([
  { $match: { id_curso: { $in: [1, 4] } } },
  { $unwind: "$valoraciones" },
  { $match: { "valoraciones.estudiante_id": 1 } },
  { $project: { _id: 0, curso: "$nombre", comentario: "$valoraciones.comentario",
                puntuacion: "$valoraciones.puntuacion", fecha: "$valoraciones.fecha" } }
])
