#Overview

Very simple search engine for demonstrations of searching within the Web Server Workshop YouTube channel.

The initial version was really put together to explain the difference between 301 vs 302 redirect response codes.  Over time, more and more features may be added.

# Features/Limits
* There is no link discovery
* The indexing is just looking for individual words and counts
* HTML tags are completely ignored
* Indexing is stored to a json file.

# Future Work
We probably should add a small flask application that we could run that reads the index.json file and allows people to actually search.
