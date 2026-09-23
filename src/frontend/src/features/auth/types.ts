/**
 * Represents user retrieved from the API.
 * @interface User
 * @property {string} id - The id of the user.
 * @property {string} email - The email of the user.
 * @property {string} name - The name of the user.
 */
export interface User {
  id: string;
  // Null for a superuser created with an admin email only.
  email: string | null;
  full_name: string | null;
  language: string;
  is_superuser: boolean;
}
