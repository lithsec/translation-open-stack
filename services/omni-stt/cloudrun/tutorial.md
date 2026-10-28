# Omnilingual hearing on Cloud Run

<walkthrough-tutorial-duration duration="45"></walkthrough-tutorial-duration>

This puts the Omnilingual hearing services in **your own** Google Cloud
project, on Cloud Run with an NVIDIA L4 GPU, scaled to zero. The script offers
three layouts:

1. **7B only** (recommended): one service, **omni-stt-7b**, Meta's 7B model on
   one L4. It hears Lao and Khmer, tells when a speaker switches into Haitian
   Creole (language ID), and speaks Haitian Creole (the voices). The Haitian
   Creole words come from Amazon Transcribe, which Live Translation starts on
   that switch. About 6 rooms at once.
2. **omni-stt only**: hears and speaks Haitian Creole with the smaller 300M
   model; about 4 rooms at once.
3. **Both**: omni-stt, plus the 7B service for Lao and Khmer (two L4s).

At the end you get the address(es) and an access token to paste into Live
Translation.

**Cost, in plain words:** about **$1 an hour per service** while it is awake
(public list price: the L4, 4 vCPU and 16 GiB), and **$0 while idle**. A
service wakes when a room needs it (about 40 seconds for omni-stt, 50 for the
7B) and goes back to sleep about 15 minutes after the last room disconnects.
Building an image in your project bills Cloud Build minutes once (a few
dollars at most). While it sleeps the only bill is image storage in Artifact
Registry ($0.10 per GB a month): about $1 a month for omni-stt, about $2-3
for the 7B.

Click **Start** to begin.

## Choose a project

<walkthrough-project-setup billing="true"></walkthrough-project-setup>

Pick (or create) the project the services will live in. It needs a billing
account: GPUs have no free tier. A project used only for this keeps the bill
easy to read.

If Cloud Shell asks you to **Authorize** gcloud, click it: the script runs as
you, in your project.

## Run the setup script

Run this in the terminal below. It asks a few questions (region, which
layout, whether you are a non-profit), shows the plan, and changes nothing
until you say yes:

```sh
PROJECT={{project-id}} bash services/omni-stt/cloudrun/setup.sh
```

What it does:

1. Checks you are signed in and the project has billing.
2. Lets you pick a region that offers Cloud Run L4 GPUs.
3. Enables the APIs it needs and checks the GPU quota.
4. Makes a service account and a random access token (kept in Secret Manager).
5. With omni-stt: gets its image, the published one, pulled through an
   Artifact Registry remote repository in your project.
6. With omni-stt: deploys it: 1 L4, at most 1 instance, 0 when idle. The
   first deploy copies the 16 GB image, about 11 minutes; gcloud may say
   "readiness deadline exceeded" meanwhile, and the script waits it out.
7. With the 7B: (Both: shows omni-stt's settings and token straight away)
   builds the 7B image once in your project with Cloud Build (about 50
   minutes) and deploys it (about 12 more minutes, again mostly the image
   copy). In the 7B-only layout it is deployed with the voices.

You can close Cloud Shell during a build: the build keeps going. Run the same
command again afterwards; the script is safe to re-run and picks up where it
stopped.

### If it stops on GPU quota

A new project sometimes has no Cloud Run L4 quota in a region. The script says
so and shows the link. In **IAM & Admin > Quotas**, filter for
"Total Nvidia L4 GPU allocation without zonal redundancy, per project per
region", pick your region, **Edit quota**, and ask for 1 (2 for the Both
layout). Then run the script again, or try another region.

## Paste into Live Translation

The script ends with a box like this:

```
Service:                               https://omni-stt-....run.app
Omnilingual 7B URL for Lao and Khmer:  https://omni-stt-7b-....run.app
Token:                                 <64 characters>
```

**Copy the token now.** It is shown only once. (Lost it? Run the script again
with `--new-token`.)

In Live Translation, open **Service settings > Advanced > Omnilingual hearing
(advanced)** and paste:

- **Service**: the omni-stt address (7B only: the 7B address).
- **Omnilingual 7B URL for Lao and Khmer**: the 7B address, if you deployed it.
- **Token**: the token (the same token works for both services).

With **7B only** both addresses are the same: the 7B service answers
everything omni-stt would (the same hearing and voice connections). For
Haitian Creole's words, give Live Translation its Amazon Transcribe setting
(or use Managed by Lithos); without that hand-off the 7B writes them itself.

Turn on **Hear Haitian Creole with Omnilingual** and press **Test**: it wakes
the service(s) and checks the token.

## Remove everything

To delete the services, the token, the service account and the images:

```sh
bash services/omni-stt/cloudrun/teardown.sh
```

It deletes only what the setup script made (they carry its label), and asks
you to type the project ID first. Shutting down the whole project also
removes everything.

## Done

<walkthrough-conclusion-trophy></walkthrough-conclusion-trophy>

The services sleep until a room needs them. Watch the cost in **Billing >
Reports**, and set a budget alert in **Billing > Budgets & alerts** if you
like. The service's own documentation is `services/omni-stt/README.md`.
