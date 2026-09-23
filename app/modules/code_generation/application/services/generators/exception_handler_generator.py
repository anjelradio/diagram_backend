from app.modules.code_generation.domain.value_objects.spring_boot_project_config import (
    GeneratedFile,
    SpringBootProjectConfig,
)


class ExceptionHandlerGenerator:
    """Generador de @RestControllerAdvice para captura global de errores conversacionales en Spring Boot."""

    def __init__(self, config: SpringBootProjectConfig) -> None:
        self.config = config

    def generate(self) -> GeneratedFile:
        package_path = self.config.package_name.replace(".", "/")
        content = f"""package {self.config.package_name}.exception;

import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.server.ResponseStatusException;
import {self.config.package_name}.dto.MessageResponse;

@RestControllerAdvice
public class GlobalExceptionHandler {{

    @ExceptionHandler(ResponseStatusException.class)
    public ResponseEntity<MessageResponse> handleResponseStatus(ResponseStatusException ex) {{
        String reason = ex.getReason() != null ? ex.getReason() : "Error al procesar la solicitud";
        return ResponseEntity.status(ex.getStatusCode()).body(new MessageResponse(reason));
    }}

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<MessageResponse> handleValidation(MethodArgumentNotValidException ex) {{
        String errorMsg = ex.getBindingResult().getFieldErrors().stream()
            .findFirst()
            .map(fe -> {{
                String defaultMsg = fe.getDefaultMessage();
                if (defaultMsg != null && !defaultMsg.isBlank()) {{
                    return defaultMsg;
                }}
                return "El campo " + fe.getField() + " es obligatorio";
            }})
            .orElse("Error de validación en los datos proporcionados");
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(new MessageResponse(errorMsg));
    }}

    @ExceptionHandler(DataIntegrityViolationException.class)
    public ResponseEntity<MessageResponse> handleDataIntegrity(DataIntegrityViolationException ex) {{
        return ResponseEntity.status(HttpStatus.BAD_REQUEST)
            .body(new MessageResponse("No se pudo completar la operación porque los datos relacionados no son válidos o faltan datos requeridos"));
    }}

    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<MessageResponse> handleIllegalArgument(IllegalArgumentException ex) {{
        String msg = ex.getMessage() != null ? ex.getMessage() : "Parámetro inválido";
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(new MessageResponse(msg));
    }}

    @ExceptionHandler(Exception.class)
    public ResponseEntity<MessageResponse> handleGeneral(Exception ex) {{
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
            .body(new MessageResponse("Ocurrió un error inesperado en el servidor"));
    }}
}}
"""
        return GeneratedFile(
            relative_path=f"src/main/java/{package_path}/exception/GlobalExceptionHandler.java",
            content=content,
        )
