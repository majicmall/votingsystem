# Render Deployment Notes

## Current production setup
- Django app: `atl_ballot`
- Start command: `gunicorn atl_ballot.wsgi:application`
- Build command: `./build.sh`
- Database: Render PostgreSQL through `DATABASE_URL`
- Static files: WhiteNoise

## Important media note
Render free services have an ephemeral filesystem. Uploaded profile pictures and nominee photos saved to `/media/` may disappear after redeploys or service restarts.

For production, connect persistent media storage later, such as:
- Cloudinary
- AWS S3
- Google Cloud Storage
- Render Disk on a paid plan

Until then, database data will persist in PostgreSQL, but uploaded media files may not be permanent.
