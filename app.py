from sklearn.linear_model import LinearRegression
import plotly.graph_objects as go
from datetime import datetime
import streamlit as st
import pandas as pd
import asyncio
import httpx


def file_load(file) -> pd.DataFrame | None:
    data = pd.read_csv(file)
    if data.get('timestamp') is None or data.get('city') is None:
        st.error('Файл неподдерживается')
        return
    data['timestamp'] = pd.to_datetime(data['timestamp']).dt.to_period('D')
    return data


def analyze_temp(data: pd.DataFrame, window=30):
    data['rolling_mean'] = data['temperature'].rolling(window=window).mean()
    data['rolling_std'] = data['temperature'].rolling(window=window).std()
    lower_bound = data['temperature'] < (data['rolling_mean'] - 2 * data['rolling_std'])
    upper_bound = data['temperature'] > (data['rolling_mean'] + 2 * data['rolling_std'])
    data['anomaly'] = lower_bound | upper_bound
    return data


async def fetch_temp(city, apikey):
    URL = 'https://api.openweathermap.org/data/2.5/weather'
    params = {'q': city, 'appid': apikey, 'units': 'metric'}
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(URL, params=params, timeout=10)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            st.error(e.response.text)
            return
        except Exception as e:
            st.error(e)
            return
        data = response.json()
        return data['main']['temp']


def get_season():
    month = datetime.now().month
    if month in [12, 1, 2]: return 'winter'
    elif month in [3, 4, 5]: return 'spring'
    elif month in [6, 7, 8]: return 'summer'
    return 'autumn'


def normal_temp(temp, city_data, season):
    season_data = city_data[city_data['season'] == season]
    mean_temp = season_data['temperature'].mean()
    std_temp = season_data['temperature'].std()
    lower_bound = mean_temp - 2 * std_temp
    upper_bound = mean_temp + 2 * std_temp
    return lower_bound <= temp <= upper_bound


def temp_trend(city_data: pd.DataFrame):
    time = city_data['timestamp']
    city_data['days'] = (time - time.min()).apply(lambda x: x.n)
    X = [[day] for day in city_data['days'].tolist()]
    y = city_data['temperature'].tolist()
    model = LinearRegression().fit(X, y)
    trend = model.coef_[0]
    return trend


async def handle_city(city, data, apikey, placeholder, use_threads=True, test=False, temp=None):
    with placeholder.container():
        if use_threads:
            city_data = await asyncio.to_thread(analyze_temp, data[data['city'] == city].copy())
        else:
            city_data = analyze_temp(data[data['city'] == city].copy())

        data_index = city_data.set_index('timestamp').to_timestamp()
        anomalies = data_index[data_index['anomaly'] == True]
        seasonal_stats = city_data.groupby('season')['temperature'].agg(['mean', 'std'])
        trend = temp_trend(city_data)
        trend_status = 'положителен' if trend > 0 else 'отрицателен'

        if apikey: temp = await fetch_temp(city, apikey)
        if temp:
            season = get_season()
            is_normal = normal_temp(temp, city_data, season)
            status = 'нормальна' if is_normal else 'аномальна'

        if test: return
        st.markdown(f"<h1 style='color: #4da4ff;'>Анализ города {city}</h1>",
                    unsafe_allow_html=True)
        opis_placeholder = st.empty()
        anomalies_placeholder = st.empty()
        chart_placeholder = st.empty()
        trend_placeholder = st.empty()
        if temp: temp_placeholder = st.empty()

        with opis_placeholder.container():
            st.write(f"Средняя температура: {city_data['temperature'].mean():.2f} °C")
            st.write(f"Минимальная температура: {city_data['temperature'].min():.2f} °C")
            st.write(f"Максимальная температура: {city_data['temperature'].max():.2f} °C")

        with anomalies_placeholder.container():
            st.header('Аномалии')
            st.write(f"Всего аномалий {city_data['anomaly'].sum()} из {len(city_data)}")
            st.dataframe(city_data[city_data['anomaly']])

        with chart_placeholder.container():
            st.header('Временной ряд температур с аномалиями')
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=data_index.index, y=data_index['temperature'],
                                     name='Температура'))
            fig.add_trace(go.Scatter(x=data_index.index, y=data_index['rolling_mean'],
                                     name='Скользящее среднее'))
            fig.add_trace(go.Scatter(x=anomalies.index, y=anomalies['temperature'],
                                     mode='markers', name='Аномалии', marker=dict(color='red', size=5)))
            st.plotly_chart(fig)

            st.header('Сезонный профиль температур')
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=seasonal_stats.index, y=seasonal_stats['mean'], mode='lines+markers',
                                     name='Средняя температура'))
            fig.add_trace(go.Scatter(x=seasonal_stats.index, y=seasonal_stats['mean'] + seasonal_stats['std'],
                                     name='+1 стандартное отклонение', line=dict(dash='dash')))
            fig.add_trace(go.Scatter(x=seasonal_stats.index, y=seasonal_stats['mean'] - seasonal_stats['std'],
                                     name='-1 стандартное отклонение', line=dict(dash='dash')))
            st.plotly_chart(fig)

            st.header('Распределение температуры')
            fig = go.Figure()
            fig.add_trace(go.Histogram(x=city_data['temperature'],
                                       marker=dict(color='lightskyblue',
                                                   line=dict(color='black', width=1)),
                                       hovertemplate='Диапазон: %{x} °C<br>Частота: %{y}<extra></extra>'))
            st.plotly_chart(fig)
        with trend_placeholder.container():
            st.header('Температурный тренд города')
            st.write(f'Тренд {trend_status}. \
                     Температура в среднем изменяется на {trend:.5f} °C в день, {trend*365:.4f} °C в год')

        if temp:
            with temp_placeholder.container():  # type: ignore
                st.header(f'Текущая температура в {city}: {temp}°C')
                st.write(f'Температура {status} для сезона {season}')  # type: ignore


async def benchmark(cities, data, apikey, placeholders, test=True):
    # Async обработка городов + распараллеленый анализ
    start_time = asyncio.get_event_loop().time()
    tasks = [handle_city(city, data, apikey, placeholders[city], test=test)
             for city in cities]
    await asyncio.gather(*tasks)
    time_sequential = asyncio.get_event_loop().time() - start_time
    st.sidebar.markdown(f'- Распараллеленая обработка городов и анализа: {time_sequential:.2f} секунд')

    # Async обработка городов
    start_time = asyncio.get_event_loop().time()
    tasks = [handle_city(city, data, apikey, placeholders[city],
                         use_threads=False, test=test) for city in cities]
    await asyncio.gather(*tasks)
    time_theards = asyncio.get_event_loop().time() - start_time
    st.sidebar.markdown(f'- Распараллеленая обработка городов: {time_theards:.2f} секунд')

    # Последовательная обработка городов
    start_time = asyncio.get_event_loop().time()
    for city in cities:
        await handle_city(city, data, apikey, placeholders[city], test=test)
    time_noasync = asyncio.get_event_loop().time() - start_time
    st.sidebar.markdown(f'- Последовательная обработка городов: {time_noasync:.2f} секунд')


async def main():
    st.title('Мониторинг и анализ погоды')
    st.sidebar.markdown('## Меню управления')
    expander = st.sidebar.expander("Настройки анализа", expanded=True)
    with expander:
        file = st.file_uploader(
            'Загрузить исторические данные о температуре', type='csv')
    if not file or (data := file_load(file)) is None: return
    with expander:
        apikey = st.text_input('Введите API Key OpenWeatherMap', type='password')
    cities = st.sidebar.multiselect('Выберите города', data['city'].unique())
    button = st.sidebar.button('Начать анализ')
    if not button: return
    placeholders = {city: st.empty() for city in cities}
    tasks = [handle_city(city, data, apikey, placeholders[city]) for city in cities]

    await asyncio.gather(*tasks)
    await benchmark(cities, data, apikey, placeholders)

if __name__ == '__main__':
    asyncio.run(main())
