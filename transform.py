import argparse
import google.cloud.storage as gcs
from datetime import datetime, timedelta
from pyspark.sql import SparkSession
from pyspark.sql.functions import udf, col, month
from pyspark.sql.types import DateType


def to_datetime(x):
    if x != None:
        return timedelta(days=x) + datetime(1960,1,1,0,0,0,0)
    else:
        return None

def transform(bucket_name):
    
    bucket = gcs.Client().get_bucket(bucket_name)

    sas_filenames = []
    for ix, key in enumerate(bucket.list_blobs(prefix='18-83510-I94-Data-2016/')):
        if ix == 0:
            df_immigration = spark.read.format('com.github.saurfang.sas.spark').load('gs://{}/{}'.format(bucket_name, key.name))
            df_immigration = df_immigration.select('arrdate', 'depdate', 'i94mon', 'i94visa',
                                        'i94port', 'i94addr', 'biryear', 'gender')
        else:
            df_temp = spark.read.format('com.github.saurfang.sas.spark').load('gs://{}/{}'.format(bucket_name, key.name) )
            df_temp = df_temp.select('arrdate', 'depdate', 'i94mon', 'i94visa',
                                        'i94port', 'i94addr', 'biryear', 'gender')
            df_immigration = df_immigration.union(df_temp)
        sas_filenames.append('gs://{}/{}'.format(bucket_name, key.name))

    df_immigration = df_immigration.select('arrdate', 'depdate', 'i94mon', 'i94visa',
                                        'i94port', 'i94addr', 'biryear', 'gender')
    to_datetime_udf = udf(to_datetime, DateType())
    df_immigration = df_immigration.withColumn('arrdate', to_datetime_udf('arrdate'))
    df_immigration = df_immigration.withColumn('depdate', to_datetime_udf('depdate'))

    # - # - # - # Demographic data # - # - # - # 
    df_demographic =spark.read.format('csv').load("gs://{}/us-cities-demographics.csv".format(bucket_name),
                                                header=True, inferSchema=True, sep=';')
    df_demographic = df_demographic.groupBy('State','State Code').avg()

    df_immigration = df_immigration.na.drop(subset=["i94addr"])
    df_immigration_2 = df_immigration.join(df_demographic,
                        df_immigration.i94addr == df_demographic['State Code'],'left')

    # - # - # - # Airport data # - # - # - #
    df_airport = spark.read.format('csv').load("gs://{}/airport-codes_csv.csv".format(bucket_name),
                                                header=True, inferSchema=True)
    df_immigration_3 = df_immigration.join(df_airport,
                                            df_immigration.i94port == df_airport['iata_code'],'left')

    # - # - # - # Temperature data # - # - # - #
    df_temperature = spark.read.format('csv').load("gs://{}/GlobalLandTemperaturesByCity.csv".format(bucket_name),
                                                    header=True, inferSchema=True)
    df_temperature = df_temperature.filter( (df_temperature.dt>datetime(2011,12,31,23,59,0,0))\
                                            & (df_temperature.dt < datetime(2013,1,1,0,0,0,0)) )

    df_immigration_3_nu = df_immigration_3.select('arrdate','depdate','municipality','i94port').dropDuplicates()
    df_immigration_3_nu = df_immigration_3_nu.na.drop(subset=["municipality"])
    df_immigration_3_nu.cache()
    df_temperature_nu = df_temperature.select('dt', 'AverageTemperature','City','Country')
    df_temperature_nu.cache()
    df_immigration_4 = df_immigration_3_nu.join(df_temperature_nu,
                                                (df_immigration_3_nu.municipality == df_temperature_nu['City']) \
                                                & (month(df_immigration_3_nu.arrdate) == month(df_temperature_nu['dt']) ), 'left')
    df_immigration_4 = df_immigration_4.select('arrdate','AverageTemperature','i94port','municipality','Country').dropDuplicates()

    df_immigration_5 = df_immigration_2.join(df_immigration_4, on=['arrdate','i94port'], how='left')
    df_immigration_5 = df_immigration_5.na.drop(subset=["AverageTemperature","municipality","Country"])

    # - # - # - # Select and rename columns # - # - # - #
    df_final = df_immigration_5.select(col("arrdate").alias("arrival_date"), col("depdate").alias("departure_date"),
                                    col("i94mon").alias("arrival_month"), col("i94port").alias("origin_airport_code"),
                                    col("i94visa").alias("visa_code"), col("i94addr").alias("stay_state"),
                                    col("municipality").alias("origin_city"),
                                    col("Country").alias("origin_country"),
                                    col("avg(Total Population)").alias("avg_population"),
                                    col("avg(Foreign-born)").alias("avg_foreign_born"), 
                                    col("avg(Average Household Size)").alias("avg_household_size"),
                                    col("avg(Median Age)").alias("avg_median_age"),
                                    col("AverageTemperature").alias("origin_avg_temperature"))
    
    output_filename = "gs://{}/I94_data_transformed_2016.parquet".format(bucket_name)
    df_final.write.save(output_filename, format="parquet", header=True)

if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("--bucket", help="bucket for input and output")
    args = parser.parse_args()

    BUCKET = args.bucket
    # spark = SparkSession.builder.\
    #     config("spark.jars.packages","saurfang:spark-sas7bdat:2.0.0-s_2.11")\
    #     .enableHiveSupport().getOrCreate()
    spark = SparkSession.builder.appName("Transform data").getOrCreate()

    transform(BUCKET)
