**Michael Herron, Full-Stack Software Developer & Automation Engineer**

With a B.S. in Computer Science from Duke University, Michael builds robust, user-centered automations and integrations. He specializes in transforming complex, scattered processes into reliable, intuitive systems designed to serve the user first–rejecting the notion of user error in favor of better, more human-oriented design. Michael designs scalable, multi-tenant architectures, integrating platforms like JobTread, QuickBooks, and GoHighLevel. He has expertise in numerous APIs and packages, with a strong foundation in PostgreSQL and database design. He also develops AI agents, using novel context engineering techniques to deliver next-generation, AI-powered solutions to clients. Outside of work, Michael enjoys snowboarding, skateboarding, and wakeboarding.

Key Changes:

* Express that I was first employee, and took a custom, service based business model and moved it to a product-based approach that can scale

Job \- Work completed:

* First employee in a service-based automation company  
* Metabase project  
  * Brainstormed how to make this into a “product”-based design– how to streamline processes and create a single offering to sell to multiple companies  
  * Learned Metabase, a SQL-like data visualization platform  
  * Learned ETL best practices – took an existing, bug-laden ETL service, fixed the issues, and updated it to support multi-tenant approach  
  * Worked directly with clients to tailor dashboards to their needs– learning to take a specific clients’ needs, find the root cause, and   
* Zapier/custom automation  
  * Created an MVP (single-tenant) integration between RingCentral and JobTread (job management software for contractors). All texts and calls were matched to one or multiple JobTread contacts. Matching calls and texts were appended to a comment thread for each matching contact, allowing contractors to establish a single source of truth   
  * Fine-grained understanding of both the RingCentral and JobTread APIs, and permissions, data structures, and data formatting on both platforms  
  * Handled complications due to limitations of Zapier in handling the RingCentral API – RingCentral’s Zapier “New Text Message” Trigger only receives messages from a single webhook  
    * pivoting to n8n for greater flexibility, creating   
* Guided company towards more scalable & maintainable automation practices and platforms  
  * Transitioned away from low/no-code platforms like Zapier and towards client-hosted n8n instances for custom projects  
  * Push away from custom projects as a whole, in favor of product-based automation design – testing this proof-of-concept with Pipedream for the speed of implementing multi-tenant automations with their “Connect” managed auth solution  
  * Architected a product-oriented, subscription-based database design for the company. Would ingest data from multiple platforms into a relational and a vector database, using relational database and [Next.js](http://Next.js) webapp for business analytics, and vector database for informed LLM chats and AI agents.  
* GoHighLevel Integration  
  * Architected and implemented a multi-tenant MVP integration between GoHighLevel and JobTread.  
    * Created an MVP solution for multi-tenant managed auth – didn’t end up leveraging Pipedream Connect  
      * For HighLevel, used an Agency OAuth token, with logic in components to request a subaccount token using the agency token  
      * For JobTread, leveraged the “Connected Organizations” feature   
  * User-driven design  
    * Learned GoHighLevel on a fine-grained level as a user, in order to design the integration in a way that was tailored to their needs  
  * Learned Pipedream on a fine-grained level  
    * Wrote custom components (as javascript with some Pipedream-specific intricacies) for almost all steps  
    * Managed memory & cost limitations   
      * refactored workflows into smaller, more modular pieces to cut costs, prevent out-of-memory errors  
    * Wrote extensive, clear, concise documentation  
* Linear \+ Project management  
  * Learned to extensively self-manage through issue tracking: with detailed names & descriptions, milestones, priorities, categories, and assignment  
  * Self-directed practice of AGILE methodologies to manage increasingly complex projects: with sprint planning, daily standups, continuous review & re-adjustment, sprint retrospectives, and more  
  * Learned to communicate technical needs clearly and concisely to leadership to ensure the team is on the same page in terms of priorities

**Maxx Potential**  
*What from your last role would help you as an apprentice?*  
I have a lot of experience in self-directed learning and user-driven design--I think that's the biggest strength. 

My last role involved coming in as the first hire to a service-based automation company, learning their stack, and figuring out how we could build a product out of it. I learned how to design scalable applications in practice: managing stakeholder & user requirements with product-based design practices, designing application frameworks, mapping out data types from external platforms for integrations, and intelligently connecting them with robust, fail-proof logic. I'll also benefit from a deep understanding of a variety of different APIs: I know how to create multi-tenant automations & integrations that handle multiple accounts for different apps for each user. I did this at Builder Clarity by designing an integration between a contractor Project Management software (JobTread) and a CRM (GoHighLevel), using Pipedream for the future extensibility with its 'Connect' managed auth feature. 

I also have a good understanding of working with LLM-assisted coding tools. I've learned how to leverage Claude Code to assist my development: identifying potential architectural issues, finding bugs more quickly, ensuring code is aligned with API specifications, and more. I know how to use Claude Code well, while still maintaining ownership of my code and ensuring that I fully understand the code I'm putting into production.

Most of all, I'm a hard worker who's able to learn and pivot quickly.  
