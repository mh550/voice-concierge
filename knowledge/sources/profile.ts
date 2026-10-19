export interface Profile {
  name: string;
  positioning: string;
  tagline: string;
  subline: string;
  location: string;
  email: string;
  linkedin: string;
  github: string;
  siteUrl: string;
  headshot: string;
  // One line shown above Selected work on /card; '' renders nothing (docs/conference-kit.md)
  conferenceNote: string;
}

// The single source of contact and positioning facts (docs/notes/brand.md). No phone number (D5).
export const profile: Profile = {
  name: 'Michael Herron',
  positioning: 'Systems & Process Engineer',
  tagline: 'I build simple, elegant systems that fit the humans who run them.',
  subline:
    'I find where work breaks down, design the system that fixes it, then build it, run it, and measure it.',
  location: 'Durham, NC',
  email: 'mherron734@gmail.com',
  linkedin: 'https://www.linkedin.com/in/mherron734/',
  github: 'https://github.com/mh550',
  siteUrl: 'https://michael-herron.vercel.app',
  headshot: '/photos/headshot.png',
  conferenceNote: "Glad we met! Here's some of what I've been building — I'd love to stay in touch.",
};
