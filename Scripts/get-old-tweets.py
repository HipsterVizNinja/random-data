import GetOldTweets3 as got

tweetCriteria = got.manager.TweetCriteria().setQuerySearch('#Heardle')\
                                           .setSince("2022-07-01")\
                                           .setUntil("2022-07-02")\
                                           .setMaxTweets(100)
tweet = got.manager.TweetManager.getTweets(tweetCriteria)[0]
print(tweet.text)