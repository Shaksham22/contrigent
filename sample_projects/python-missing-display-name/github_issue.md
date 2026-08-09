# Handle users without a display name

The `get_display_name` function currently assumes every user has a
`display_name`.

Some imported users have `display_name=None`, which causes the function to
fail.

## Expected behavior

If `display_name` is available, return it.

If `display_name` is missing, fall back to the user's username.

## Examples

A user with:

- username: `shaksham`
- display_name: `Shaksham Shubham`

should return:

`SHAKSHAM SHUBHAM`

A user with:

- username: `shaksham`
- display_name: `None`

should return:

`shaksham`