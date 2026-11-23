# Viewer chat room

An optional public chat room in the viewer's left column. Anyone can read.
To post, a visitor signs in (Google, Facebook, or email and password) and
picks a username.

The chat runs on a separate hosted service, a [Supabase](https://supabase.com)
project that you own. It holds the accounts, passwords and messages. It has
no connection to the ShadowBroker engine: it never sees map data, API keys or
the engine machine. If no chat service is configured, the viewer has no chat
and no sign-in at all.

## What protects it

- **Passwords** go from the visitor's browser straight to the login service
  over https. The viewer site never stores them.
- **Database rules** (`schema.sql`) decide everything a visitor may do:
  post only as themselves, only after picking a username, at most one
  message every 3 seconds and 10 a minute, 500 characters, plain text.
  Nobody can make themselves a moderator or un-ban themselves.
- **The key in the site is public by design.** The build refuses a service
  or secret key, so the powerful one can never be published by accident.
- **The viewer's network rule** gains one narrow exception: reads and posts
  to the chat service's login and data paths. Edits, deletes and every other
  path on that host stay refused, and nothing else is loosened.
- **Messages are shown as plain text.** No HTML, no clickable links.

## Set it up (about 20 minutes, once)

1. Create a project at supabase.com. Pick any region.
2. Open **SQL Editor**, paste all of `schema.sql`, run it.
3. **Authentication > Sign In / Providers**
   - Email: leave on. Keep **Confirm email** on.
   - Google: turn on, and paste the client ID and secret from a Google Cloud
     OAuth client (Supabase shows the redirect address to give Google).
   - Facebook: optional, same idea. Facebook reviews apps before the public
     can use them, so start without it.
4. **Authentication > URL Configuration**: set **Site URL** to the viewer's
   address, and add it to **Redirect URLs**.
5. **Authentication > Attack Protection**: turn on CAPTCHA (Turnstile or
   hCaptcha). It blocks bulk sign-ups. *(The viewer does not show a CAPTCHA
   box yet; add that before enabling this, or sign-ups will fail.)*
6. **Project Settings > API**: copy the **Project URL** and the **anon**
   (publishable) key into `viewer/web/chat.config.json`:

   ```json
   {
     "url": "https://YOUR-PROJECT.supabase.co",
     "anonKey": "the anon / publishable key",
     "providers": ["google"]
   }
   ```

   Never put the `service_role` or secret key anywhere in this repo. The
   build stops if it sees one.
7. Build the viewer (`node viewer/web/build.mjs`) and publish it.
8. Sign in once, pick your username, then make yourself a moderator in the
   SQL editor:

   ```sql
   update public.profiles set is_mod = true where username = 'your_name';
   ```

## Moderating

In the Supabase table editor:

- hide a message: set `hidden` to true on its row in `messages`;
- ban an account: set `banned` to true on its row in `profiles`;
- see what people flagged: the `reports` table;
- trim old messages: `select public.chat_prune();` (older than 30 days).

## Before you open it to the public

- Publish a short privacy note: the chat collects an email address and
  shows the chosen username and messages publicly.
- Decide who moderates and how often.
- The room refreshes by asking the service for new messages every 5 seconds
  while the panel is open. That is fine for a small room; a busy one should
  move to the service's push feed.

## Try it locally without any account

```bash
node viewer/chat/mock-server.mjs          # prints a test anon key
# put that url + key in viewer/web/chat.config.json, then:
node viewer/web/build.mjs && node viewer/web/serve.mjs
```

The stand-in keeps everything in memory and applies the same posting rules.
Its "Google" button signs in a fixed test person. It is for development only.
