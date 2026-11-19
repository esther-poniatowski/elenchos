/** An input that breaks the findings profile, such as a location name that no producer writes. */
export class ProfileError extends Error {
  override readonly name = "ProfileError";
}
