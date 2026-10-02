# CI/CD: disponible, comprobado y pendiente de autorización

## Funcionamiento preparado

En `.github/workflows/ci.yml`, el job `test` prueba Python 3.11 y 3.12 y conserva
la salida de unittest. Solo después de que ambos pasen puede ejecutarse `deploy`.
Se admite exclusivamente el repositorio `guillecubas/GraphWord`, la rama
`refactor/python-distributed` y eventos que no sean pull requests.

El despliegue está desactivado por defecto. Se activa únicamente si existen las
variables de repositorio `ENABLE_AWS_DEPLOY=true`, `AWS_DEPLOY_ROLE_ARN` y
`AWS_ACCOUNT_ID`. No contienen claves secretas. OIDC obtiene credenciales temporales;
no copiamos la sesión de Academy a GitHub. La acción comprueba la cuenta esperada.

`scripts/ci_deploy.py` despliega el commit comprobado, enciende sus nodos, espera
SSM, verifica cloud-init y systemd, realiza el smoke HTTP y pide detener los nodos
en un bloque `finally`. No cancela despliegues anteriores automáticamente.
El resultado es una demostración desplegada y verificada, no un servicio 24/7.
Los artefactos `aws-deployment-<SHA>` conservan metadatos y resultados, no claves.

Un runner terminado por fuerza, credenciales caducadas o una actualización
CloudFormation incompleta pueden impedir la parada: revisar la pila y EC2 tras un
fallo. Si CloudFormation falla antes de devolver IDs, el script no adivina qué
máquinas detener. La parada no elimina EBS, S3, DynamoDB ni sus posibles costes.

## Bloqueo observado en Academy (2 de octubre de 2026)

La consulta IAM no devolvió proveedores OIDC. La confianza de `LabRole` no incluye
GitHub. La simulación de permisos del rol de laboratorio devolvió `implicitDeny`
para `iam:CreateRole`, `iam:CreateOpenIDConnectProvider` e `iam:PutRolePolicy`.
Esto no demuestra todos los permisos posibles, pero no hay una vía autorizada
disponible para crear la integración. No se ha modificado IAM ni se ha activado CD.

**CI automática y despliegue manual real sí están disponibles. CD desde GitHub
queda preparado, pero no validado extremo a extremo y pendiente de administrador.**
No se presenta un job omitido como una prueba de despliegue exitosa.

## Qué debe hacer el administrador

1. Autorizar expresamente esta integración en una cuenta apta para CI/CD y revisar
   costes, permisos, cuotas y la política educativa. No ampliar indiscriminadamente
   la confianza de `LabRole` ni conceder `AdministratorAccess`.
2. Crear/reutilizar el proveedor `https://token.actions.githubusercontent.com` con
   audiencia `sts.amazonaws.com` y un rol dedicado. Adaptar
   `infra/github-oidc-trust.example.json` con la cuenta y el `sub` exacto emitido
   para este repositorio/rama. Según la fecha/configuración de GitHub, el `sub`
   puede incluir IDs de propietario/repositorio; no sustituirlo por un comodín.
3. Revisar permisos de despliegue: CloudFormation sobre `graphword-storage` y
   `graphword-compute`; lectura de VPC/subred/AMI; creación y gestión de las EC2 y
   su grupo de seguridad; S3 para bucket/artefactos; DynamoDB, SQS y logs de las
   plantillas; SSM sobre los nodos etiquetados GraphWord; `iam:GetInstanceProfile`
   y `iam:PassRole` solo para el rol EC2 autorizado y `ec2.amazonaws.com`.
   Ajustar ARN, condiciones y acciones a las plantillas y política de la cuenta.
   La plantilla de confianza no es una política de permisos de recursos.
4. Crear las tres variables indicadas. Proteger la rama y revisar cambios en
   workflows/scripts: quien modifica código de despliegue puede usar su rol.
5. Ejecutar un push o `workflow_dispatch` de esa rama. Confirmar ambos tests,
   identidad, pila, smoke HTTP y parada de EC2. Revisar CloudTrail ante denegaciones;
   conceder solo las acciones justificadas. Conservar el enlace y artefactos del run.

Si el profesor no puede autorizarlo, entregar la limitación documentada y solicitar
aceptación de CI + despliegue reproducible manual, o una cuenta/entorno autorizado.

Referencia técnica: [acción oficial de credenciales AWS](https://github.com/aws-actions/configure-aws-credentials)
y [OIDC con AWS en GitHub](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws).
