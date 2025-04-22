# Secret Keys/Passwords and Rotation Info:

 Goal is for all secrets to be encrypted, and rotating annually (automatically if possible)

 If you are adding/changing a secret for this service, please update the documentation here and on this audit inventory:  
 https://confluence.bbpd.io/display/LRNCTL/Microservices+Secret+Inventory+and+Rotation+Info

 Notes:
 * There are currently no secrets needing to be rotated for this service
 * There are several keys used for CI builds such as ARTIFACTORY_TOKEN and AWS_CODE_ARTIFACT_READ_ONLY_ACCESS_KEY_ID and a dev registrar key/secret used for API tests.  However, these are not deployed with the service and don't allow access to prod data, so no need to rotate.


 | Secret Name           | Encrypted | Encryption Type | Rotation  | How to rotate    | Description                                                                                                      |
 | --------------------- | --------- | --------------- | --------- | ---------------- | ---------------------------------------------------------------------------------------------------------------- |